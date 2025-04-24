import json
import boto3
from boto3.dynamodb.conditions import Key
import time
import os
import openai
from dotenv import load_dotenv

load_dotenv()

# Servicios AWS
bedrock = boto3.client('bedrock-runtime', region_name='eu-central-1')
bedrock_agent = boto3.client('bedrock-agent-runtime')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('memory-chatbot-python-rag')
kb_client = boto3.client("bedrock-agent-runtime")

#Clave openai
openai.api_key = os.environ.get("OPENAI_API_KEY")

def lambda_handler(event, context):
    """Función lambda encargada de responder las preguntas del usuario utilizando Bedrock Knowledge Base"""

    try:
        body = json.loads(event["body"])
        user_query = body.get("query", "")
        session_id = body.get("session_id", "")
        selected_model = body.get("model", "bedrock")

        if not user_query or not session_id:
            return {
                "statusCode": 400,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*"
                },
                "body": json.dumps({"error": "Missing query or session_id"})
            }

        #Aplicar filtro de guardaraíles
        guardrail_response = bedrock.apply_guardrail(
            guardrailIdentifier=os.environ.get('GUARDRAIL_ID'),
            guardrailVersion='1',  
            source='INPUT',
            content=[{
                'text': {
                    'text': user_query
                }
            }]
        )
        print(guardrail_response)

        if guardrail_response['action'] == 'GUARDRAIL_INTERVENED':
            return {
                "statusCode": 200,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*"
                },
                "body": json.dumps({"response": "Lo siento, pero únicamente puedo contestar preguntas sobre lenguajes de programación o conceptos tecnológicos relacionados.\nReformule su pregunta e inténtelo de nuevo."})
            }

        #Clasificar pregunta del usuario
        prompt_clasification = classificate_prompt_agent(user_query, session_id)

        if prompt_clasification == 'COMPLEX':
            # Obtener historial de conversación
            conversation_history = get_conversation_history(session_id)

            # Obtener chunks relevantes de 'Knowledge Base'
            content_list, metadata_list = retrieve_from_kb(user_query)
            localizaciones = []  
            references = "\nReferencias:\n"
            for meta in metadata_list:
                uri = meta['source_uri']
                if uri and uri not in localizaciones:
                    localizaciones.append(uri)
                    url = get_public_url(uri)
                    page = meta['page_number']
                    references += f"- {url} (Página {page})\n"

            # Añadirlos al prompt
            formatted_prompt = format_complex_prompt(user_query, content_list, conversation_history)

            # Pasar el prompt al bedrock para que genere la respuesta
            if selected_model == "bedrock":
                response = query_bedrock(formatted_prompt)#Claude
                model_response = response['content'][0]['text']#Claude

            elif selected_model == "openai":
                model_response = openai_response(formatted_prompt, user_query)#openAI

            model_response += "\n"
            model_response += references
            print(f"Respuesta del modelo: {model_response}")

        elif prompt_clasification == 'SIMPLE':
            # Obtener historial de conversación
            conversation_history = get_conversation_history(session_id)

            # Añadirlos al prompt
            formatted_prompt = format_simple_prompt(user_query, conversation_history)

            # Pasar el prompt al bedrock para que genere la respuesta
            if selected_model == "bedrock":
                response = query_bedrock(formatted_prompt)#Claude
                model_response = response['content'][0]['text']#Claude
            elif selected_model == "openai":
                model_response = openai_response(formatted_prompt, user_query) #openAI
            print(f"Respuesta del modelo: {model_response}")

        elif prompt_clasification == 'NULL':
            model_response = "Lo siento, pero únicamente puedo contestar preguntas sobre lenguajes de programación o conceptos tecnológicos relacionados.\nReformule su pregunta e inténtelo de nuevo."
        else:
            model_response = "El agente no clasificó correctamente, vuelva a intentarlo."

        # Almacenar la interacción en DynamoDB
        store_interaction(session_id, user_query, model_response)

        # Return con la respuesta del modelo
        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*"
            },
            "body": json.dumps({"response": model_response})
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*"
            },
            "body": json.dumps({"error": str(e)})
        }

def classificate_prompt_agent(user_prompt, session_id):
    kwargs = {
            "agentAliasId": os.environ.get('AGENT_ALIAS_ID'),
            "agentId": os.environ.get('AGENT_ID'),
            "sessionId": session_id,
            "inputText": "Classify into 'NULL', 'SIMPLE' or 'COMPLEX': '" + user_prompt + "' Just tell if it is 'NULL', 'SIMPLE' or 'COMPLEX'."
        }

    response = bedrock_agent.invoke_agent(**kwargs)

    # Check if the response contains 'completion' which is an EventStream object
    if 'completion' in response:
        event_stream = response['completion']
        agent_response = ""
        # Iterate over the stream and inspect each chunk
        for chunk in event_stream:
            print("Chunk:", chunk)  # Debug: Log each chunk to see its structure
            if 'chunk' in chunk and 'bytes' in chunk['chunk']:
                agent_response += chunk['chunk']['bytes'].decode('utf-8')
            else:
                print("Unexpected chunk structure:", chunk)
        if not agent_response:
            agent_response = "No valid response content found in the stream"
    else:
        agent_response = "No completion found in the response"
    
    return agent_response.strip()

def get_conversation_history(session_id):
    """Retrieve the last 5 interactions for the session from DynamoDB."""

    try:
        response = table.query(
            KeyConditionExpression=Key('session_id').eq(session_id),
            Limit=5,  #Número de interacciones
            ScanIndexForward=False  #Coge las 5 últimas y no las 5 primeras
        )
        return response.get('Items', [])
    except Exception as e:
        print(f"Error retrieving conversation history: {e}")
        return []

def retrieve_from_kb(query):
    """Retrieve relevant chunks from the Knowledge Base."""

    try:
        response = kb_client.retrieve(
            guardrailConfiguration={
                'guardrailId': os.environ.get('GUARDRAIL_ID'),
                'guardrailVersion': '1'
            },
            knowledgeBaseId=os.environ.get('KB_ID'),
            retrievalQuery={"text": query}
        )
        chunks = response["retrievalResults"][:3]  # Número de chunks obtenidos = 3

        content_list = []
        metadata_list = []

        for idx, chunk in enumerate(chunks):
            content_list.append(chunk["content"]["text"])
            page_number = chunk.get("metadata").get("x-amz-bedrock-kb-document-page-number")
            metadata_list.append({
                "source_uri": chunk.get("metadata").get("x-amz-bedrock-kb-source-uri"),
                "page_number": int(page_number)
            })

        return content_list, metadata_list

    except Exception as e:
        print(f"Error retrieving from Knowledge Base: {e}")
        return []

def format_complex_prompt(query, content_list, conversation_history):
    """Format the prompt with RAG context and conversation history."""

    # Formato historial
    history = "\n\n".join([
        f"User: {item['user_query']}\nBot: {item['model_response']}"
        for item in conversation_history
    ])

    # Formato chunks
    context = "\n".join([f"Chunk {i+1}: {text}" for i, text in enumerate(content_list)]) if content_list else "No hay información adicional."
    
    # Formato del prompt
    prompt = (
        "### 🖥️ [INSTRUCCIONES PARA EL CHATBOT DE PROGRAMACIÓN] 🖥️\n\n"
        
        "### 🎯 ÁMBITO TEMÁTICO:\n"
        "Habla **solo** de temas relacionados con **lenguajes de programación** (Python, JavaScript, C, C++, etc.) y conceptos afines (algoritmos, estructuras de datos, etc.). 💻\n\n"
        
        "### 🗣️ TONO Y ESTILO:\n"
        "- Usa el **tuteo** y un lenguaje **neutro, cercano y claro**.\n"
        "- Añade **emojis tecnológicos** (ej. 💻, 🖥️, 👩‍💻, 🚀, 🔍,🐍,✔️,❌,⚠️,⛔) para hacerlo más dinámico.\n"
        "- Estructura las respuestas con **viñetas**, **numeración** o **saltos de línea** para que sean fáciles de leer.\n"
        "- Sé **amable, motivador y profesional**, como un **mentor en programación**.\n\n"
        
        "### 📌 ENFOQUE Y CONTENIDO:\n"
        "- Responde de forma **clara, práctica y estructurada**.\n"
        "- Usa el **historial** y el **contexto relevante** para dar respuestas precisas.\n"
        "- Si el contexto no es suficiente, di: 'No tengo datos suficientes para responderte bien.'\n"
        "- Ofrece **ejemplos concretos**, trucos útiles o consejos prácticos.\n"
        
        "### Historial de Conversación:\n"
        f"{history}\n\n"
        
        "### Contexto Relevante de la Base de Conocimiento:\n"
        f"{context}\n\n"
        
        "### Instrucciones:\n"
        "- Responde **solo** a la pregunta del usuario sin agregar información innecesaria.\n"
        "- Usa el historial solo como referencia, únicamente cuando sea necesario y **no inventes nuevas conversaciones**.\n"
        "- **Si el historial no es relevante**, ignóralo y responde directamente a la pregunta.\n"
        "- **Mantén tu respuesta breve y relevante.**\n"
        "Ten muy en cuenta las instrucciones proporcionadas\n\n"
        f"Pregunta del Usuario: {query}\n\n"
        "Tu Respuesta:"
    )

    print(prompt)  #Debugging
    return prompt

def format_simple_prompt(query, conversation_history):
    """Format the prompt with RAG context and conversation history."""

    # Formato historial
    history = "\n\n".join([
        f"User: {item['user_query']}\nBot: {item['model_response']}"
        for item in conversation_history
    ])

    # Formato del prompt
    prompt = (
        "### 🖥️ [INSTRUCCIONES PARA EL CHATBOT DE PROGRAMACIÓN] 🖥️\n\n"
        
        "### 🎯 ÁMBITO TEMÁTICO:\n"
        "Habla **solo** de temas relacionados con **lenguajes de programación** (Python, JavaScript, C, C++, etc.) y conceptos afines (algoritmos, estructuras de datos, etc.). 💻\n\n"
        
        "### 🗣️ TONO Y ESTILO:\n"
        "- Usa el **tuteo** y un lenguaje **neutro, cercano y claro**.\n"
        "- Añade **emojis tecnológicos** (ej. 💻, 🖥️, 👩‍💻, 🚀, 🔍,🐍,✔️,❌,⚠️,⛔) para hacerlo más dinámico.\n"
        "- Estructura las respuestas con **viñetas**, **numeración** o **saltos de línea** para que sean fáciles de leer.\n"
        "- Sé **amable, motivador y profesional**, como un **mentor en programación**.\n\n"

        "### Historial de Conversación:\n"
        f"{history}\n\n"
        
        "### Instrucciones:\n"
        "- Responde **solo** a la pregunta del usuario sin agregar información innecesaria.\n"
        "- Usa el historial solo como referencia, únicamente cuando sea necesario y **no inventes nuevas conversaciones**.\n"
        "- **Si el historial no es relevante**, ignóralo y responde directamente a la pregunta.\n"
        "- **Mantén tu respuesta breve y relevante.**\n"
        "Ten muy en cuenta las instrucciones proporcionadas\n\n"
        f"Pregunta del Usuario: {query}\n\n"
        "Tu Respuesta:"
    )

    print(prompt)  #Debugging
    return prompt

def query_bedrock(prompt):
    """Send the prompt to the Bedrock model."""

    try:
        kwargs = {
            "modelId": os.environ.get('MODEL_ID'),  
            "contentType": "application/json",
            "accept": "application/json",
            "body": json.dumps({
                "anthropic_version": "bedrock-2023-05-31", 
                "max_tokens": 1000,  
                "temperature": 0.4,  
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            })
        }

        '''kwargs = {
            "modelId": os.environ.get('MODEL_ID'),
            "contentType": "application/json",
            "accept": "*/*",
            "body": json.dumps(
                {
                    "inputText": prompt,
                    "textGenerationConfig": {
                        "temperature": 0.4,
                        "maxTokenCount": 1000
                    }
                }
            )
        } Para amazon lite'''

        response = bedrock.invoke_model(**kwargs)
        bedrock_output = json.loads(response['body'].read().decode('utf-8'))
        print(bedrock_output)
        return bedrock_output

    except Exception as e:
        print(f"Error querying Bedrock: {e}")
        raise e

def store_interaction(session_id, user_query, model_response):
    """Store the interaction in DynamoDB."""

    try:
        table.put_item(
            Item={
                'session_id': session_id,
                'timestamp': int(time.time()),
                'user_query': user_query,
                'model_response': model_response
            }
        )
    except Exception as e:
        print(f"Error storing interaction in DynamoDB: {e}")

def get_public_url(s3_uri):
    """Convierte una URI de S3 en una URL pública."""
    try:
        if not s3_uri.startswith("s3://"):
            return "URL no disponible"
        # Extraer bucket y path
        bucket = s3_uri.split('/')[2]
        path = '/'.join(s3_uri.split('/')[3:])
        region = "eu-central-1"
        # Construir URL pública
        public_url = f"https://{bucket}.s3.{region}.amazonaws.com/{path}"
        return public_url
    except Exception as e:
        print(f"Error generando URL pública: {str(e)}")
        return "URL no disponible"
    
def openai_response(prompt, user_query):
    response = openai.ChatCompletion.create(
        model = "gpt-4.1-mini",
        messages = [
            {"role":"system", "content" : prompt},
            {"role": "user", "content": user_query}
        ],
        max_tokens=1000,
        temperature=0.4, 
        top_p=1.0
    )

    model_response = response.choices[0].message.content.strip()
    print(f"Respuesta de OpenAI: {model_response}")
    return model_response
    
#Funcion main para hacer pruebas en local sin el CLI. No añadir a la lambda desplegada en AWS
if __name__ == "__main__":
    event = {"body": json.dumps({"query": "Que es un match en python?", "session_id": "test-session", "model": "bedrock"})}
    response = lambda_handler(event, None)
    print(response["body"])