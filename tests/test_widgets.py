from nf_marimo.widgets.process import ProcessWidget


def test_process_widget(pipeline):
    upper = pipeline.processes[0]
    w = ProcessWidget(upper)
    assert w.title == "UPPER"
    assert w.module == "local/upper"
    assert [i["key"] for i in w.inputs] == ["text", "suffix"]
    assert all(i["connected"] for i in w.inputs)
    assert [o["emit"] for o in w.outputs] == ["txt"]
    assert w.status == "not run"
    upper.results = {"txt": [[{"id": "s1"}, "/tmp/s1.txt"]]}
    w.refresh()
    assert w.status == "done"
    assert w.results == {"txt": ["[[id:s1], /tmp/s1.txt]"]}
