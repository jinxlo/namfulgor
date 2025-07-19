# namwoo_app/create_openai_assistant.py
import os
import sys
import logging
from openai import OpenAI
from dotenv import load_dotenv

# This is the original, correct import when run as a module
try:
    from services.tools_schema import tools_schema
except ImportError as e:
    print(f"\nERROR: Could not import 'tools_schema'.\n"
          f"HINT: Run this script as a module from the project root inside Docker:\n"
          f"docker exec <container_name> python3 -m create_openai_assistant\n\n"
          f"Details: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_namfulgor_assistant():
    basedir = os.path.abspath(os.path.dirname(__file__))
    dotenv_path = os.path.join(basedir, '.env')
    load_dotenv(dotenv_path=dotenv_path)
    logging.info("Loaded environment variables...")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logging.error("CRITICAL: OPENAI_API_KEY not found in .env file.")
        return

    client = OpenAI(api_key=api_key)

    try:
        prompt_file_path = os.path.join(basedir, "data", "system_prompt.txt")
        with open(prompt_file_path, "r", encoding="utf-8") as f:
            prompt_content = f.read()
        logging.info(f"Successfully read system prompt from: {prompt_file_path}")
    except FileNotFoundError:
        logging.error(f"CRITICAL: Could not find system_prompt.txt at: {prompt_file_path}")
        return

    logging.info("Sending request to OpenAI to create Assistant 'Serviauto Supremo'...")
    try:
        assistant = client.beta.assistants.create(
            name="Serviauto Supremo (NamFulgor)",
            instructions=prompt_content,
            tools=tools_schema,
            model="gpt-4o-mini"
        )
        logging.info(f"Assistant created with ID: {assistant.id}")

        print("\n" + "="*50)
        print("✅ OpenAI Assistant Created Successfully!")
        print(f"   Assistant ID: {assistant.id}")
        print("="*50)
        print("\n>>> ACTION REQUIRED <<<\n")
        print("Copy the Assistant ID above and add it to your .env file as:")
        print(f"OPENAI_ASSISTANT_ID={assistant.id}\n")

    except Exception as e:
        logging.error(f"Failed to create Assistant on OpenAI's servers. Error: {e}", exc_info=True)

if __name__ == "__main__":
    create_namfulgor_assistant()