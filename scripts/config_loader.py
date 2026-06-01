#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OPC 配置加载器
支持 YAML 配置文件 + 环境变量覆盖
"""

import os
import re
from pathlib import Path
from typing import Any

# 尝试导入 yaml
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    print("警告: 未安装 PyYAML,请运行: pip install pyyaml")


class Config:
    """配置管理类"""

    def __init__(self, config_path: str = None):
        """
        初始化配置

        Args:
            config_path: 配置文件路径,默认从 OPC_ROOT 环境变量推断
        """
        self._config = {}
        self._raw_config = {}

        # 确定配置文件路径
        if config_path is None:
            opc_root = os.environ.get('OPC_ROOT', 'D:\\opc')
            config_path = os.path.join(opc_root, 'config.yaml')

        self.config_path = config_path
        self._opc_root = os.environ.get('OPC_ROOT', 'D:\\opc')

        # 加载配置
        self._load_config()
        self._apply_env_overrides()

    def _load_config(self):
        """加载 YAML 配置文件"""
        if not HAS_YAML:
            print("警告: PyYAML 未安装,使用默认配置")
            self._config = self._default_config()
            return

        config_file = Path(self.config_path)
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    self._raw_config = yaml.safe_load(f)
                    self._config = self._expand_env_vars(self._raw_config)
                print(f"[OK] 已加载配置: {config_file}")
            except Exception as e:
                print(f"[ERROR] 加载配置失败: {e}")
                self._config = self._default_config()
        else:
            print(f"[WARN] 配置文件不存在: {config_file},使用默认配置")
            self._config = self._default_config()

    def _expand_env_vars(self, obj: Any) -> Any:
        """递归展开配置中的环境变量"""
        if isinstance(obj, dict):
            return {k: self._expand_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._expand_env_vars(item) for item in obj]
        elif isinstance(obj, str):
            # 支持 ${VAR} 和 $VAR 两种格式
            def replace_env(match):
                var_name = match.group(1) or match.group(2)
                env_value = os.environ.get(var_name, '')
                return env_value

            # 匹配 ${VAR} 或 $VAR
            expanded = re.sub(r'\$\{(\w+)\}|\$(\w+)', replace_env, obj)
            return expanded
        return obj

    def _apply_env_overrides(self):
        """应用环境变量覆盖"""
        # API密钥
        if os.environ.get('DEEPSEEK_API_KEY'):
            self._set_nested('api.deepseek.key', os.environ['DEEPSEEK_API_KEY'])

        if os.environ.get('MPTEXT_API_KEY'):
            self._set_nested('api.mptext.key', os.environ['MPTEXT_API_KEY'])

        if os.environ.get('GITHUB_TOKEN'):
            self._set_nested('git.token', os.environ['GITHUB_TOKEN'])

        # 路径覆盖
        if os.environ.get('OPC_ROOT'):
            self._opc_root = os.environ['OPC_ROOT']
            self._set_nested('paths.root', self._opc_root)
            # 使用 os.path.join 确保跨平台路径正确
            self._set_nested('paths.knowledge_base', os.path.join(self._opc_root, 'knowledge-base'))
            self._set_nested('paths.drafts', os.path.join(self._opc_root, 'drafts'))
            self._set_nested('paths.reviewed', os.path.join(self._opc_root, 'reviewed'))
            self._set_nested('paths.ready_to_publish', os.path.join(self._opc_root, 'ready-to-publish'))
            self._set_nested('paths.raw_articles', os.path.join(self._opc_root, 'raw-articles'))
            self._set_nested('paths.logs', os.path.join(self._opc_root, 'logs'))

        # 日志级别
        if os.environ.get('LOG_LEVEL'):
            self._set_nested('logging.level', os.environ['LOG_LEVEL'])

    def _set_nested(self, key_path: str, value: Any):
        """设置嵌套配置值"""
        keys = key_path.split('.')
        current = self._config
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value

    def _get_nested(self, key_path: str, default: Any = None) -> Any:
        """获取嵌套配置值"""
        keys = key_path.split('.')
        current = self._config
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        获取配置值

        Args:
            key_path: 点分隔的配置路径,如 'api.deepseek.key'
            default: 默认值

        Returns:
            配置值或默认值
        """
        return self._get_nested(key_path, default)

    def get_path(self, key_path: str) -> Path:
        """
        获取路径配置

        Args:
            key_path: 点分隔的配置路径

        Returns:
            Path对象
        """
        path_str = self.get(key_path, '')
        # 处理路径分隔符，确保跨平台兼容
        path_str = path_str.replace('/', os.sep).replace('\\', os.sep)
        return Path(path_str)

    @property
    def opc_root(self) -> Path:
        """OPC根目录"""
        return Path(self._opc_root)
    
    @opc_root.setter
    def opc_root(self, value: str):
        """设置OPC根目录"""
        self._opc_root = value
        # 更新路径配置
        self._set_nested('paths.root', self._opc_root)
        self._set_nested('paths.knowledge_base', os.path.join(self._opc_root, 'knowledge-base'))
        self._set_nested('paths.drafts', os.path.join(self._opc_root, 'drafts'))
        self._set_nested('paths.reviewed', os.path.join(self._opc_root, 'reviewed'))
        self._set_nested('paths.ready_to_publish', os.path.join(self._opc_root, 'ready-to-publish'))
        self._set_nested('paths.raw_articles', os.path.join(self._opc_root, 'raw-articles'))
        self._set_nested('paths.logs', os.path.join(self._opc_root, 'logs'))

    @property
    def knowledge_base_dir(self) -> Path:
        """知识库目录"""
        return Path(os.path.join(self._opc_root, 'knowledge-base'))

    @property
    def drafts_dir(self) -> Path:
        """草稿目录"""
        return Path(os.path.join(self._opc_root, 'drafts'))

    @property
    def reviewed_dir(self) -> Path:
        """审稿目录"""
        return Path(os.path.join(self._opc_root, 'reviewed'))

    @property
    def ready_to_publish_dir(self) -> Path:
        """待发布目录"""
        return Path(os.path.join(self._opc_root, 'ready-to-publish'))

    @property
    def raw_articles_dir(self) -> Path:
        """原始文章目录"""
        return Path(os.path.join(self._opc_root, 'raw-articles'))

    @property
    def logs_dir(self) -> Path:
        """日志目录"""
        return Path(os.path.join(self._opc_root, 'logs'))

    @property
    def deepseek_api_key(self) -> str:
        """DeepSeek API密钥"""
        return self.get('api.deepseek.key', '')

    @property
    def deepseek_api_url(self) -> str:
        """DeepSeek API URL"""
        return self.get('api.deepseek.url', 'https://api.deepseek.com/v1/chat/completions')

    @property
    def deepseek_model(self) -> str:
        """DeepSeek模型"""
        return self.get('api.deepseek.model', 'deepseek-chat')

    @property
    def mptext_api_key(self) -> str:
        """mptext API密钥"""
        return self.get('api.mptext.key', '')

    @property
    def github_token(self) -> str:
        """GitHub Token"""
        return self.get('git.token', '')

    @property
    def github_repo(self) -> str:
        """GitHub仓库"""
        return self.get('git.repo', 'diandengwa/opc-agent-knowledge')

    @property
    def min_score(self) -> float:
        """最低通过分数"""
        return float(self.get('pipeline.generation.min_score', 8.0))

    @property
    def max_attempts(self) -> int:
        """最大尝试次数"""
        return int(self.get('pipeline.generation.max_attempts', 2))

    @property
    def default_count(self) -> int:
        """默认生成数量"""
        return int(self.get('pipeline.generation.default_count', 2))

    @property
    def channels(self) -> list:
        """分发渠道"""
        return self.get('pipeline.generation.channels', ['公众号', '小红书', '朋友圈', '微信群'])

    @property
    def xiaoshengchu_ratio(self) -> float:
        """小升初比例约束"""
        return float(self.get('pipeline.generation.constraints.xiaoshengchu_ratio', 0.7))

    @property
    def min_word_count(self) -> int:
        """最小字数"""
        return int(self.get('pipeline.generation.constraints.min_word_count', 800))

    @property
    def max_word_count(self) -> int:
        """最大字数"""
        return int(self.get('pipeline.generation.constraints.max_word_count', 1500))

    @property
    def title_min_length(self) -> int:
        """标题最小长度"""
        return int(self.get('pipeline.generation.title.min_length', 12))

    @property
    def title_max_length(self) -> int:
        """标题最大长度"""
        return int(self.get('pipeline.generation.title.max_length', 18))

    @property
    def forbidden_suffixes(self) -> list:
        """禁止的标题后缀"""
        return self.get('pipeline.generation.title.forbidden_suffixes',
                       ['实操指南', '避坑指南', '完全解读', '全面解析'])

    @property
    def static_keywords(self) -> list:
        """静态内容关键词"""
        return self.get('pipeline.generation.static_keywords',
                       ['养成计划', '30天', '习惯养成', '遛娃', '亲子互动',
                        '不花钱的', '比手机管用', '暑假', '夏令营', '阅读计划'])

    @property
    def ai_smell_keywords(self) -> list:
        """AI味关键词"""
        return self.get('pipeline.generation.ai_smell_keywords',
                       ['赋能', '抓手', '闭环', '沉淀', '方法论', '底层逻辑',
                        '认知升级', '降维打击', '生态', '赛道', '矩阵',
                        '值得关注的是', '不得不提', '不得不说',
                        '让我们拭目以待', '未来可期'])

    def _default_config(self) -> dict:
        """默认配置"""
        return {
            'paths': {
                'root': self._opc_root,
                'knowledge_base': os.path.join(self._opc_root, 'knowledge-base'),
                'drafts': os.path.join(self._opc_root, 'drafts'),
                'reviewed': os.path.join(self._opc_root, 'reviewed'),
                'ready_to_publish': os.path.join(self._opc_root, 'ready-to-publish'),
                'raw_articles': os.path.join(self._opc_root, 'raw-articles'),
                'logs': os.path.join(self._opc_root, 'logs'),
            },
            'api': {
                'deepseek': {
                    'key': '',
                    'url': 'https://api.deepseek.com/v1/chat/completions',
                    'model': 'deepseek-chat',
                },
                'mptext': {
                    'key': '',
                    'url': 'https://api.mptext.com/v1',
                },
            },
            'git': {
                'repo': 'diandengwa/opc-agent-knowledge',
                'branch': 'main',
                'token': '',
            },
            'pipeline': {
                'generation': {
                    'min_score': 8.0,
                    'max_attempts': 2,
                    'default_count': 2,
                    'channels': ['公众号', '小红书', '朋友圈', '微信群'],
                    'constraints': {
                        'xiaoshengchu_ratio': 0.7,
                        'min_word_count': 800,
                        'max_word_count': 1500,
                    },
                    'title': {
                        'min_length': 12,
                        'max_length': 18,
                        'forbidden_suffixes': ['实操指南', '避坑指南', '完全解读', '全面解析'],
                    },
                    'static_keywords': ['养成计划', '30天', '习惯养成', '遛娃', '亲子互动',
                                       '不花钱的', '比手机管用', '暑假', '夏令营', '阅读计划'],
                    'ai_smell_keywords': ['赋能', '抓手', '闭环', '沉淀', '方法论', '底层逻辑',
                                           '认知升级', '降维打击', '生态', '赛道', '矩阵',
                                           '值得关注的是', '不得不提', '不得不说',
                                           '让我们拭目以待', '未来可期'],
                },
            },
        }


# 全局配置实例
_config_instance = None

def get_config(config_path: str = None) -> Config:
    """
    获取全局配置实例(单例模式)

    Args:
        config_path: 配置文件路径

    Returns:
        Config实例
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = Config(config_path)
    return _config_instance


def reload_config(config_path: str = None) -> Config:
    """
    重新加载配置

    Args:
        config_path: 配置文件路径

    Returns:
        Config实例
    """
    global _config_instance
    _config_instance = Config(config_path)
    return _config_instance


if __name__ == '__main__':
    # 测试配置加载
    config = get_config()

    print(f"OPC Root: {config.opc_root}")
    print(f"Knowledge Base: {config.knowledge_base_dir}")
    print(f"Drafts: {config.drafts_dir}")
    print(f"DeepSeek Key: {'*' * 10 if config.deepseek_api_key else '未设置'}")
    print(f"Min Score: {config.min_score}")
    print(f"Channels: {config.channels}")
    print(f"Forbidden Suffixes: {config.forbidden_suffixes}")
