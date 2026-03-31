"""Single source of truth for application configuration.

All environment variable keys, defaults, and descriptions live here.
Import get_config() to retrieve the full configuration dict.
"""

import os


def get_config():
    """Return a dict with all environment-variable-driven settings the app needs.

    Each key maps to the value currently set in the environment,
    falling back to the documented default when the variable is unset.
    """
    return {
        # BytePlus ModelArk API key (required)
        "ARK_API_KEY": os.getenv("ARK_API_KEY", "YOUR_API_KEY_HERE"),

        # Base URL for the Ark API (video, image, file endpoints derive from this)
        "ARK_API_BASE": os.getenv("ARK_API_BASE", "https://ark.ap-southeast.bytepluses.com/api/v3"),

        # Set to "0" or "false" to disable SSL verification (useful behind proxy/firewall)
        "ARK_SSL_VERIFY": os.getenv("ARK_SSL_VERIFY", "1"),

        # LLM chat-completions endpoint used by builder.py for prompt generation
        "ARK_LLM_URL": os.getenv("ARK_LLM_URL", "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions"),

        # Seedance 2.0 model identifier (update from ModelArk console when new versions ship)
        "SEEDANCE_2_MODEL_ID": os.getenv("SEEDANCE_2_MODEL_ID", "seedance-2-0-pro-260210"),

        # Seedream 5.0-lite model identifier
        "SEEDREAM_5_MODEL_ID": os.getenv("SEEDREAM_5_MODEL_ID", "seedream-5-0-260128"),
    }
