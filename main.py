import sentientmilk_framework
from dotenv import load_dotenv
import os
import inspect

load_dotenv()

BASE_URL = os.getenv("BASE_URL", None)
API_KEY = os.getenv("API_KEY", None)


client = sentientmilk_framework.LLM(API_KEY, BASE_URL, "qwen/qwen3.5-397b-a17b")

print(client.loaded_tools)