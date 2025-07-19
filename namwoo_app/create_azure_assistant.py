# namwoo_app/create_azure_assistant.py
import os
import sys
import logging
from openai import AzureOpenAI
from dotenv import load_dotenv

# Add the app directory to Python path
sys.path.insert(0, '/usr/src/app')

try:
    # Instead of importing directly, we'll execute the tools_schema file with a patched Config
    # First, create a mock Config class
    class Config:
        ENABLE_LEAD_GENERATION_TOOLS = True
    
    # Read and execute tools_schema.py with the relative import removed
    with open('/usr/src/app/services/tools_schema.py', 'r') as f:
        tools_schema_code = f.read()
    
    # Replace the problematic relative import
    tools_schema_code = tools_schema_code.replace('from ..config import Config', '')
    
    # Execute the modified code to get tools_schema
    exec(tools_schema_code)
    
except Exception as e:
    print(f"\nERROR: Could not load 'tools_schema'.\n"
          f"Details: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_azure_namfulgor_assistant():
    # ... the rest of the file is correct and does not need to change ...
    basedir = os.path.abspath(os.path.dirname(__file__))
    dotenv_path = os.path.join(basedir, '.env')
    load_dotenv(dotenv_path=dotenv_path)
    logging.info("Loaded environment variables...")

    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION")
    model_deployment_name = os.getenv("AZURE_OPENAI_ASSISTANT_MODEL_DEPLOYMENT_NAME")

    if not all([azure_endpoint, api_key, api_version, model_deployment_name]):
        logging.error("CRITICAL: One or more required Azure environment variables are missing.")
        return

    client = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=azure_endpoint
    )

    try:
        prompt_file_path = os.path.join(basedir, "data", "system_prompt.txt")
        with open(prompt_file_path, "r", encoding="utf-8") as f:
            prompt_content = f.read()
        logging.info(f"Successfully read system prompt from: {prompt_file_path}")
    except FileNotFoundError:
        logging.error(f"CRITICAL: Could not find system_prompt.txt at: {prompt_file_path}")
        return

    logging.info(f"Sending request to Azure OpenAI to create Assistant on deployment '{model_deployment_name}'...")
    try:
        assistant = client.beta.assistants.create(
            name="Serviauto Supremo (NamFulgor Azure)",
            instructions=prompt_content,
            tools=tools_schema,
            model=model_deployment_name
        )
        logging.info(f"Azure Assistant created with ID: {assistant.id}")

        print("\n" + "="*50)
        print("✅ Azure Assistant Created Successfully!")
        print(f"   Assistant ID: {assistant.id}")
        print("="*50)
        print("\n>>> ACTION REQUIRED <<<\n")
        print("Copy the Assistant ID above and add it to your .env file as:")
        print(f"AZURE_OPENAI_ASSISTANT_ID={assistant.id}\n")

    except Exception as e:
        logging.error(f"Failed to create Assistant on Azure's servers. Error: {e}", exc_info=True)

if __name__ == "__main__":
    create_azure_namfulgor_assistant()