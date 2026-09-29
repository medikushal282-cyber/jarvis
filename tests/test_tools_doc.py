import pytest
from pathlib import Path

def test_tools_doc_freshness():
    """Verify that config/tools.md is up-to-date with the tool manifests."""
    root_dir = Path(__file__).parent.parent
    
    # Import the generator
    import sys
    sys.path.append(str(root_dir / "scripts"))
    from generate_tools_doc import generate_tools_doc
    
    expected_content = generate_tools_doc(root_dir)
    
    doc_path = root_dir / "config" / "tools.md"
    assert doc_path.exists(), "config/tools.md does not exist. Run scripts/generate_tools_doc.py"
    
    with open(doc_path, "r", encoding="utf-8") as f:
        actual_content = f.read()
        
    assert actual_content == expected_content, (
        "config/tools.md is out of date. "
        "Please run `python scripts/generate_tools_doc.py` and commit the changes."
    )
