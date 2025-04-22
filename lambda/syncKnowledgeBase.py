import json
import boto3
import time

#Agente bedrock
bedrock_client = boto3.client("bedrock-agent", region_name="eu-central-1")

#Constantes
KB_ID = "X8CQAGVDFK"
DATASOURCE_ID = "1QM5UFQ4J4"

def lambda_handler(event, context):
    """Función para sincronizar los datasources de una Knowledge Base al subir un fichero nuevo"""

    s3_bucket = event["Records"][0]["s3"]["bucket"]["name"]
    file_key = event["Records"][0]["s3"]["object"]["key"]
    
    print(f"New file uploaded: s3://{s3_bucket}/{file_key}")

    sync_job = bedrock_client.start_ingestion_job(
        knowledgeBaseId=KB_ID,
        dataSourceId=DATASOURCE_ID
    )

    job_id = sync_job["ingestionJob"]["ingestionJobId"]
    print(f"Started Sync Job: {job_id}")

    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Sync started", "file": file_key, "job_id": job_id})
    }