import json
import boto3
import uuid
import base64

s3 = boto3.client("s3")
BUCKET_NAME = "bedrock-rag-prueba"

def lambda_handler(event, context):
    """Gestiona la carga de archivos desde Streamlit y los guarda en S3."""
    try:
        if "body" not in event:
            return {"statusCode": 400, "body": json.dumps({"error": "Missing request body"})}

        body = json.loads(event["body"])
        file_content = base64.b64decode(body.get("file_content", ""))
        file_name = body.get("file_name", str(uuid.uuid4()) + ".txt")

        # Subir archivo a S3
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=f"documents/userUploads/{file_name}",  
            Body=file_content
        )

        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*",
            },
            "body": json.dumps({"message": "File uploaded successfully", "file_name": file_name}),
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*",
            },
            "body": json.dumps({"error": str(e)}),
        }
