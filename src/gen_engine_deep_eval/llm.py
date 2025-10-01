from langchain_core.output_parsers import JsonOutputParser

from .wrapper import GenerativeEngineLLM
from .models import GenerativeEngineResponse


def _gen_engine_parser(data: dict) -> GenerativeEngineResponse:
    data["session_id"] = data.pop("sessionId")
    return GenerativeEngineResponse(**data)


def generate_chain(llm: GenerativeEngineLLM):
    return llm | JsonOutputParser() | _gen_engine_parser


def llm_app(llm: GenerativeEngineLLM, input: str):
    def _generator(input: str):
        chain = generate_chain(llm)
        response = chain.invoke(input)
        return {"response": response.content}

    return _generator(input)
