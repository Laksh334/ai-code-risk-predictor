"""A2 - Static analysis."""

import ast

from pipeline.static_analysis import (analyze_repository, analyze_source, coupling_and_tests, duplication,
                                      max_nesting_depth, module_name)


def test_nesting_ignores_elif_chains():
    code = ("def f(x):\n    if x == 1:\n        pass\n    elif x == 2:\n        for i in x:\n"
            "            while i:\n                pass\n    elif x == 3:\n        pass\n")
    assert max_nesting_depth(ast.parse(code)) == 3


def test_module_names():
    assert module_name("src/requests/models.py") == "requests.models"
    assert module_name("src/requests/__init__.py") == "requests"


def test_coupling_resolves_relative_imports():
    files = {
        "src/pkg/__init__.py": "from .models import Thing\nfrom . import utils\n",
        "src/pkg/models.py": "from .utils import helper\nimport os\n",
        "src/pkg/utils.py": "def helper(): return 1\n",
        "src/pkg/sub/deep.py": "from ..models import Thing\n",
        "tests/test_models.py": "from pkg.models import Thing\n",
    }
    df = coupling_and_tests(files).set_index("file_path")
    assert df.loc["src/pkg/models.py", "fan_in"] == 2  # __init__ + sub/deep (tests don't count)
    assert df.loc["src/pkg/utils.py", "fan_in"] == 2
    assert df.loc["src/pkg/models.py", "test_importers"] == 1
    assert df.loc["src/pkg/models.py", "has_test_file"]


def test_duplication_detects_copy_paste():
    block = "\n".join(f"    x{i} = compute({i}) + other({i})" for i in range(8))
    d = duplication({"a.py": f"def a():\n{block}\n", "b.py": f"def b():\n{block}\n", "c.py": "def c():\n    return 2\n"})
    assert d["a.py"] > 80 and d["b.py"] > 80 and d["c.py"] == 0


def test_python2_code_still_gets_complexity():
    r = analyze_source("old.py", 'def g(a, b):\n    print "py2"\n    if a:\n        return b\n')
    assert r["parse_ok"] is False and r["max_complexity"] == 2 and r["maintainability"] is None


def test_analyze_repository_at_head_and_in_the_past(repo):
    now = analyze_repository(repo["path"]).set_index("file_path")
    past = analyze_repository(repo["path"], rev="2022-06-01").set_index("file_path")
    assert "pkg/new_name.py" in now.index and "pkg/old_name.py" in past.index
    assert now.loc["pkg/core.py", "max_complexity"] > past.loc["pkg/core.py", "max_complexity"]
    assert now.loc["pkg/utils.py", "fan_out"] == 1  # imports pkg.core
