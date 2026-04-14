from src.auditmcp import get_calculation_network


def test_concept_as_parent(mini_filing_dir):
    net = get_calculation_network(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:Liabilities",
    )
    assert net.is_isolated is False
    assert net.as_child == []
    assert len(net.as_parent) == 1
    role = net.as_parent[0]
    assert role.role == "http://example.com/role/BalanceSheet"
    concepts = sorted(c.concept for c in role.children)
    assert concepts == ["us-gaap:Deposits", "us-gaap:OtherLiabilities"]
    assert all(c.weight == 1.0 for c in role.children)


def test_concept_as_child(mini_filing_dir):
    net = get_calculation_network(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:Deposits",
    )
    assert net.is_isolated is False
    assert net.as_parent == []
    assert len(net.as_child) == 1
    cr = net.as_child[0]
    assert cr.parent == "us-gaap:Liabilities"
    sibling_names = sorted(s.concept for s in cr.siblings)
    assert sibling_names == ["us-gaap:Deposits", "us-gaap:OtherLiabilities"]


def test_isolated_concept(mini_filing_dir):
    net = get_calculation_network(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:NonCalcItem",
    )
    assert net.is_isolated is True
    assert net.as_parent == []
    assert net.as_child == []
    assert "http://example.com/role/BalanceSheet" in net.roles_scanned
