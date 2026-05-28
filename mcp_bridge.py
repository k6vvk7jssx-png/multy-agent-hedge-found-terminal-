import os
import asyncio
import logging
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def mcp_brave_search_async(query: str) -> str:
    brave_api_key = os.getenv("BRAVE_API_KEY")
    if not brave_api_key:
        return "ERROR: BRAVE_API_KEY non trovata nel file .env. Crea una chiave gratuita su https://brave.com/search/api/ e aggiungila."
    
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-brave-search"],
        env={**os.environ, "BRAVE_API_KEY": brave_api_key}
    )
    
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                # Chiamata al tool di ricerca esposto dal server MCP
                result = await session.call_tool(
                    "brave_web_search",
                    arguments={"query": query, "count": 10}
                )
                
                if hasattr(result, "content") and isinstance(result.content, list):
                    texts = [item.text for item in result.content if hasattr(item, "text")]
                    return "\n".join(texts)
                return str(result)
    except Exception as e:
        logger.error(f"MCP Bridge Error durante la ricerca '{query}': {e}")
        return f"ERROR in MCP execution: {str(e)}"

def mcp_brave_search(query: str) -> str:
    """Wrapper sincrono per l'uso all'interno dei Tool di CrewAI"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    if loop.is_running():
        import nest_asyncio
        nest_asyncio.apply()
        
    return loop.run_until_complete(mcp_brave_search_async(query))

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    print("Testing MCP Bridge (Brave Search)...")
    res = mcp_brave_search("Tesla stock sentiment site:twitter.com")
    print(res)
