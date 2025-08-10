from mlx_lm import load, generate
from typing import List, Dict
import sys

def main() -> int:
    model, tokenizer = load("mlx-community/GLM-4.5-Air-4bit")

    prompt: str = "In German, people say 'Schoenen Tag noch'. Why do they say 'noch'?"

    if tokenizer.chat_template is not None:
        messages: List[Dict[str, str]] = [{"role": "user", "content": prompt}]
        prompt = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True
        )

    response = generate(model, tokenizer, prompt=prompt, verbose=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
