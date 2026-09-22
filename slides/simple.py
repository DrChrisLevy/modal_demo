import modal

app = modal.App("basic-function")

@app.function()
def f(x: int, exp: int) -> int:
    return x**exp

@app.local_entrypoint()
def main(exp: int = 2):
    for i in f.map(range(200), [exp] * 200):
        print(i)
