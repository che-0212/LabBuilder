"""
Protocol Planner Configuration

Configure your API settings here or use .env file.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 添加utils目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'utils'))

# 加载.env文件
load_dotenv()

# 导入全局LLM配置
try:
    from utils.llm_config import DEFAULT_API_KEY, DEFAULT_BASE_URL
except ImportError:
    DEFAULT_API_KEY = None
    DEFAULT_BASE_URL = None


class PlannerConfig:
    """Configuration for Protocol Planner"""
    
    # ==================== API Configuration ====================
    
    # 优先级: 环境变量 > 全局配置 > 默认值
    # OpenAI API Key
    API_KEY = os.environ.get('OPENAI_API_KEY') or DEFAULT_API_KEY or 'your-api-key-here'
    
    # API Base URL
    BASE_URL = os.environ.get('OPENAI_BASE_URL') or DEFAULT_BASE_URL
    
    # Model name
    MODEL = 'gpt-4o'  # Options: 'gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', etc.
    
    # ==================== Generation Parameters ====================
    
    # Temperature (0.0 - 2.0)
    # Lower values (0.1-0.3) = more deterministic, focused
    # Higher values (0.7-1.0) = more creative, varied
    TEMPERATURE = 0.3
    
    # Maximum tokens for response
    MAX_TOKENS = 4000
    
    # ==================== File Paths ====================
    
    # Asset library path (complete asset library)
    ASSET_LIBRARY_PATH = 'assets_annotated.json'
    
    # Output directory for generated protocols
    OUTPUT_DIR = 'DATA/protocols'
    
    # ==================== Validation Settings ====================
    
    # Whether to validate asset names against library
    VALIDATE_ASSETS = True
    
    # Whether to check for forbidden zones
    CHECK_FORBIDDEN_ZONES = True
    
    # ==================== Helper Methods ====================
    
    @classmethod
    def get_api_key(cls):
        """Get API key with validation"""
        api_key = cls.API_KEY
        if api_key == 'your-api-key-here':
            # Try environment variable
            api_key = os.environ.get('OPENAI_API_KEY')
            if not api_key:
                raise ValueError(
                    "API key not configured. Please either:\n"
                    "1. Set OPENAI_API_KEY environment variable, or\n"
                    "2. Edit planner_config.py and set API_KEY"
                )
        return api_key
    
    @classmethod
    def print_config(cls):
        """Print current configuration (hiding API key)"""
        print("Current Configuration:")
        print(f"  Model: {cls.MODEL}")
        print(f"  Temperature: {cls.TEMPERATURE}")
        print(f"  Max Tokens: {cls.MAX_TOKENS}")
        print(f"  Base URL: {cls.BASE_URL or 'Default OpenAI'}")
        print(f"  Asset Library: {cls.ASSET_LIBRARY_PATH}")
        print(f"  Output Directory: {cls.OUTPUT_DIR}")
        api_key = cls.API_KEY
        if api_key and api_key != 'your-api-key-here':
            masked_key = api_key[:8] + '...' + api_key[-4:] if len(api_key) > 12 else '***'
            print(f"  API Key: {masked_key}")
        else:
            print(f"  API Key: Not configured")


def get_layout_config():
    """Get LLM config for layout generation"""
    from utils.llm_config import LLMConfig
    
    try:
        api_key = PlannerConfig.get_api_key()
    except ValueError:
        # Fall back to defaults defined in utils.llm_config
        api_key = None
    
    return LLMConfig(
        api_key=api_key,
        base_url=PlannerConfig.BASE_URL,
        model=PlannerConfig.MODEL,
        temperature=PlannerConfig.TEMPERATURE,
        max_tokens=PlannerConfig.MAX_TOKENS
    )

