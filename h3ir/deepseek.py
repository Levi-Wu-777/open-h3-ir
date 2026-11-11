"""使用 Infisical 账号配置调用 DeepSeek。"""
from __future__ import annotations

from dataclasses import replace

from .config import (DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, DEEPSEEK_SECRET_NAME,
                     DEEPSEEK_SECRET_PATH, DEEPSEEK_TIMEOUT_SECONDS, Config, get_config, set_config)


def configure_deepseek() -> Config:
    from share.infisical import read_secret

    cfg = get_config()
    return replace(cfg, llm=replace(
        cfg.llm, base_url=DEEPSEEK_BASE_URL, model=DEEPSEEK_MODEL,
        api_key=read_secret(DEEPSEEK_SECRET_PATH, DEEPSEEK_SECRET_NAME),
        default_thinking=False, timeout_s=DEEPSEEK_TIMEOUT_SECONDS))


def main() -> int:
    from .cli import main as cli_main

    set_config(configure_deepseek())
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
