"""Idempotently create the configured RAG database/container and blob container."""
import asyncio
import json
from app.rag.service import rag_service


async def main():
    result = await rag_service.initialize()
    health = await rag_service.health()
    print(json.dumps({'resources': result, 'health': health}, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
