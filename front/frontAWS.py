import streamlit as st
import requests
import uuid  
import base64

# 🔹 AWS API Gateway Configuration 
BASE_URL = "https://dkjn2gd5f8.execute-api.eu-central-1.amazonaws.com/dev" #Actualmente se puede acceder a la interfaz pero las conexiones con los recursos se encuentran apagadas.
CHATBOT_FUNCTION = f"{BASE_URL}/chatbot"
UPLOAD_DOCUMENT_FUNCTION = f"{BASE_URL}/upload"

# 🔹 Generate a unique session_id (persists during session)
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())  # Unique session per user

# 🔹 Streamlit UI Configuration
st.set_page_config(page_title="AWS Chatbot AI", page_icon="🤖", layout="centered")
st.title("🤖 Chatbot con AWS Lambda & Bedrock")

# ➤ File Upload Section
with st.expander("📤 Subir documentos", expanded=False):
    st.markdown("Sube archivos PDF, TXT o JSON para agregarlos al Knowledge Base.")
    uploaded_files = st.file_uploader("Selecciona archivos", type=["pdf", "txt", "json"], accept_multiple_files=True)

    if uploaded_files and st.button("Subir documentos"):
        with st.spinner("Subiendo documentos..."):
            for file in uploaded_files:
                file_content = base64.b64encode(file.getvalue()).decode("utf-8")  # ✅ Convertir a Base64
                payload = {
                    "file_name": file.name,
                    "file_content": file_content
                }
                response_upload = requests.post(UPLOAD_DOCUMENT_FUNCTION, json=payload)

                if response_upload.status_code == 200:
                    st.success(f"Documento {file.name} subido exitosamente.")
                else:
                    st.error(f"Error al subir {file.name}: {response_upload.text}")

# 🔹 Model Selection
st.sidebar.header("⚙️ Configuración del Modelo")
model_options = {
    "Claude (Bedrock)": "bedrock",
    "GPT-4.1-mini (OpenAI)": "openai"
}
selected_model = st.sidebar.selectbox(
    "Elige el modelo para las respuestas:",
    list(model_options.keys()),
    index=0  # Por defecto, Claude
)

# 🔹 Chat History Initialization
if "messages" not in st.session_state:
    st.session_state.messages = []

# 🔹 Display Chat History
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 🔹 User Input
user_input = st.chat_input("Escribe tu mensaje...")

if user_input:
    with st.chat_message("user"):
        st.markdown(user_input)

    # Store message in session history
    st.session_state.messages.append({"role": "user", "content": user_input})

    # Prepare request payload (including session_id)
    payload = {
        "query": user_input,
        "session_id": st.session_state.session_id,
        "model": model_options[selected_model]
    }

    # Call AWS Lambda via API Gateway
    with st.spinner(f"Esperando respuesta del {selected_model}..."):
        response = requests.post(CHATBOT_FUNCTION, json=payload)

    if response.status_code == 200:
        ai_reply = response.json().get("response", "No se recibió respuesta.")
        with st.chat_message("assistant"):
            st.markdown(ai_reply)

        # Save response in session history
        st.session_state.messages.append({"role": "assistant", "content": ai_reply})
    else:
        st.error(f"Error en la respuesta del chatbot: {response.text}")