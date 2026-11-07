import marimo

__generated_with = "0.25.2"
app = marimo.App()

with app.setup:
    import os


@app.cell
def _():
    import marimo as mo
    import nf_marimo as nfm

    return mo, nfm


@app.cell
def _(nfm):
    pipeline = nfm.pipeline('x')
    x = 1
    return pipeline, x


@app.cell
def _(pipeline, x):
    def helper(a):
        return a + x
    y = helper(2)
    for _i in range(3):
        pass
    pipeline
    return


@app.function
def util(v):
    return v + 1


@app.cell(hide_code=True)
def _(mo, y):
    mo.md(f"# Title {y}")
    return


if __name__ == "__main__":
    app.run()
