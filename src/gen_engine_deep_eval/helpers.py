def get_model_provider(model: str):
    if "gemini" in model:
        return "vertexai"

    if "openai" in model:
        return "azure"

    if model.startswith("liquid"):
        return "liquidai"

    return "bedrock"
