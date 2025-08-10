from mlx_lm import load, generate

model, tokenizer = load("mlx-community/GLM-4.5-Air-4bit")

prompt = "In German, people say 'Schoenen Tag noch'. Why do they say 'noch'?"

if tokenizer.chat_template is not None:
    messages = [{"role": "user", "content": prompt}]
    prompt = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True
    )

response = generate(model, tokenizer, prompt=prompt, verbose=True)

# ai: add a main wrapper
# 
