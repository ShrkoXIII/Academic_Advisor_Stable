"""Complete synthetic sets test evaluation candidates, never production activation."""
import hashlib
import itertools
import json

import numpy as np
import pandas as pd
import pytest

from tests.unit.test_balance_policy import compute, courses


def ranking_api():
    from src.recommendation.ranking import (
        RankingStrategy, canonical_plan_identity, rank_academic_reference, rank_evaluation_plans,
    )
    return RankingStrategy, canonical_plan_identity, rank_academic_reference, rank_evaluation_plans


def metric_row(name, quality, failed, *, balanced=True, scope=True):
    identity = ranking_api()[1]([name])
    balance = compute(courses(3 if balanced else 6, 0, 12 if balanced else 9), semester=1 if scope else 3)
    return {**balance, "plan_id": identity.plan_id, "course_tuple": identity.course_tuple,
            "expected_quality_points": quality, "expected_failed_credits": failed,
            "expected_plan_gpa": quality / 15,
            "projected_cumulative_gpa": (120 + quality) / 75}


def ranked(frame, stage="stage1", name="balance_first"):
    strategy, _, _, evaluate = ranking_api()
    return evaluate(frame, strategy=strategy(stage=stage, name=name))


def names(frame):
    return [value[0] for value in frame.course_tuple]


def test_identity_is_canonical_sha256_and_includes_optional_zero_course():
    identity_fn = ranking_api()[1]
    identity = identity_fn(["B", "A", "ذ"])
    expected_json = json.dumps(["A", "B", "ذ"], ensure_ascii=False, separators=(",", ":"))
    assert identity.course_tuple == ("A", "B", "ذ")
    assert identity.canonical_json == expected_json
    assert identity.plan_id == hashlib.sha256(expected_json.encode("utf-8")).hexdigest()
    for permutation in itertools.permutations(["B", "A", "ذ"]):
        assert identity_fn(permutation) == identity
    assert identity_fn(["A", "ZERO"]).plan_id != identity_fn(["A"]).plan_id
    assert identity_fn([123.0, " B "]) == identity_fn(["123", "B"])


@pytest.mark.parametrize("values", [[], [None], [""], ["A", "A"], [123, "123.0"], [True]])
def test_invalid_plan_identity_is_rejected(values):
    with pytest.raises(ValueError):
        ranking_api()[1](values)


@pytest.mark.parametrize("stage", ["stage1", "final"])
@pytest.mark.parametrize("strategy", ["balance_first", "pareto"])
def test_balance_changes_rank_despite_different_gpa_and_failures(stage, strategy):
    # Trade-off: better balance sacrifices both GPA and expected failed credits.
    frame = pd.DataFrame([metric_row("academic", 54, .1, balanced=False), metric_row("balanced", 48, .9)])
    before = ranking_api()[2](frame, stage=stage)
    after = ranked(frame, stage, strategy)
    assert names(before) == ["academic", "balanced"]
    assert names(after) == ["balanced", "academic"]
    for column in ("expected_quality_points", "expected_failed_credits", "projected_cumulative_gpa"):
        assert after.set_index("plan_id")[column].to_dict() == frame.set_index("plan_id")[column].to_dict()
    metadata = after.attrs["ranking_strategy"]
    assert metadata["stage"] == stage
    assert metadata["name"] == strategy
    assert metadata["approval_status"] == "UNAPPROVED"


@pytest.mark.parametrize("stage", ["stage1", "final"])
@pytest.mark.parametrize("strategy", ["balance_first", "pareto"])
def test_academic_changes_with_equal_balance_and_balance_changes_with_equal_academics(stage, strategy):
    frame = pd.DataFrame([metric_row("low", 45, .4), metric_row("high", 51, .2)])
    assert names(ranked(frame, stage, strategy)) == ["high", "low"]
    frame.loc[0, ["expected_quality_points", "expected_plan_gpa", "projected_cumulative_gpa"]] = [54, 3.6, 174 / 75]
    frame.loc[0, "expected_failed_credits"] = .1
    assert names(ranked(frame, stage, strategy)) == ["low", "high"]
    frame = pd.DataFrame([metric_row("unbalanced", 45, .4, balanced=False), metric_row("balanced", 45, .4)])
    assert names(ranked(frame, stage, strategy)) == ["balanced", "unbalanced"]


@pytest.mark.parametrize("stage", ["stage1", "final"])
@pytest.mark.parametrize("strategy", ["balance_first", "pareto"])
def test_mixed_scope_preserves_ineligible_positions_in_academic_reference(stage, strategy):
    frame = pd.DataFrame([metric_row("out-high", 60, .1, scope=False),
        metric_row("academic", 54, .2, balanced=False), metric_row("out-middle", 51, .3, scope=False),
        metric_row("balanced", 48, .4), metric_row("out-low", 42, .5, scope=False)])
    assert names(ranked(frame, stage, strategy)) == ["out-high", "balanced", "out-middle", "academic", "out-low"]


@pytest.mark.parametrize("stage", ["stage1", "final"])
@pytest.mark.parametrize("strategy", ["balance_first", "pareto"])
def test_new_only_with_no_positive_repeat_candidates_keeps_reference(stage, strategy):
    frame = pd.DataFrame([metric_row("high", 54, .8), metric_row("low", 48, .1)])
    balance = compute(courses(0, 0, 15))
    for key, value in balance.items():
        frame[key] = [value, value]
    assert names(ranked(frame, stage, strategy)) == names(ranking_api()[2](frame, stage=stage))


@pytest.mark.parametrize("stage", ["stage1", "final"])
def test_balance_key_priority_is_failed_then_total_then_withdrawn(stage):
    frame = pd.DataFrame([metric_row("failed-worse", 60, 0), metric_row("total-worse", 57, .1),
                          metric_row("withdrawn-worse", 54, .2), metric_row("best", 48, .3)])
    for i, penalties in enumerate([(.1, 0, 0), (0, .1, 0), (0, 0, .1), (0, 0, 0)]):
        frame.at[i, "component_active_flags"] = {"failed": True, "total_previous": True, "withdrawn": True}
        for key, penalty in zip(("failed", "total_previous", "withdrawn"), penalties):
            frame.at[i, f"{key}_balance_penalty"] = penalty
    assert names(ranked(frame, stage)) == ["best", "withdrawn-worse", "total-worse", "failed-worse"]


def oracle_fronts(frame):
    """Independent repeated nondominance peeling on a complete small set."""
    remaining = list(range(len(frame)))
    levels = {}
    level = 0
    active = [name for name in ("failed", "total_previous", "withdrawn")
              if frame.iloc[0].component_active_flags[name]]
    values = [(-r.projected_cumulative_gpa, r.expected_failed_credits,
               *(getattr(r, f"{name}_balance_penalty") for name in active))
              for r in frame.itertuples()]
    while remaining:
        front = [i for i in remaining if not any(
            all(a <= b for a, b in zip(values[j], values[i])) and
            any(a < b for a, b in zip(values[j], values[i])) for j in remaining if j != i)]
        for i in front:
            levels[frame.iloc[i].plan_id] = level
        remaining = [i for i in remaining if i not in front]
        level += 1
    return levels


@pytest.mark.parametrize("stage", ["stage1", "final"])
def test_pareto_fronts_and_complete_selection_match_independent_oracle(stage):
    frame = pd.DataFrame([metric_row("academic", 54, .1, balanced=False),
        metric_row("balanced", 48, .5), metric_row("dominated", 42, .9, balanced=False),
        metric_row("best-balanced", 51, .4), metric_row("tie", 51, .4)])
    result = ranked(frame, stage, "pareto")
    expected_fronts = oracle_fronts(frame)
    assert result.set_index("plan_id").pareto_front.to_dict() == expected_fronts
    academic = (lambda r: (-r.expected_quality_points, r.expected_failed_credits, r.course_tuple)) if stage == "stage1" else (
        lambda r: (-r.projected_cumulative_gpa, r.expected_failed_credits, -r.expected_plan_gpa, r.plan_id))
    expected = sorted(frame.to_dict("records"), key=lambda r: (
        expected_fronts[r["plan_id"]], r["failed_balance_penalty"], r["total_previous_balance_penalty"], *academic(type("Row", (), r))))
    assert result.plan_id.tolist() == [r["plan_id"] for r in expected]
    assert len(result) == len(frame)
    assert result.pareto_front.tolist() == sorted(result.pareto_front.tolist())


@pytest.mark.parametrize("stage", ["stage1", "final"])
def test_withdrawn_is_an_independent_pareto_dominance_dimension(stage):
    low = courses(0, 3, 12).assign(course_id=["lf", "lw", "ln"])
    high = courses(0, 4, 11).assign(course_id=["hf", "hw", "hn"])
    eligible = pd.concat([low, high])
    frame = pd.DataFrame([{**metric_row("low-withdrawn", 48, .2), **compute(low, eligible)},
                          {**metric_row("high-withdrawn", 48, .2), **compute(high, eligible)}])
    assert frame.total_previous_balance_penalty.tolist() == [0, 0]
    assert frame.withdrawn_balance_penalty.iloc[0] < frame.withdrawn_balance_penalty.iloc[1]
    assert all(not flags["failed"] for flags in frame.component_active_flags)
    result = ranked(frame, stage, "pareto")
    assert dict(zip(names(result), result.pareto_front)) == {"low-withdrawn": 0, "high-withdrawn": 1}
    assert result.set_index("plan_id").pareto_front.to_dict() == oracle_fronts(frame)


@pytest.mark.parametrize("stage", ["stage1", "final"])
@pytest.mark.parametrize("strategy", ["balance_first", "pareto"])
def test_full_ties_have_total_order_independent_of_input_and_index(stage, strategy):
    frame = pd.DataFrame([metric_row(name, 48, .2) for name in ("C", "A", "B")])
    expected = sorted(frame.course_tuple) if stage == "stage1" else sorted(frame.plan_id)
    for permutation in itertools.permutations(range(len(frame))):
        permuted = frame.iloc[list(permutation)].copy()
        permuted.index = [9] * len(permuted)
        result = ranked(permuted, stage, strategy)
        assert (result.course_tuple.tolist() if stage == "stage1" else result.plan_id.tolist()) == expected


def test_independent_stage_strategies_can_differ_without_approval_or_defaults():
    strategy_cls, _, _, evaluate = ranking_api()
    first = strategy_cls(stage="stage1", name="balance_first")
    final = strategy_cls(stage="final", name="pareto")
    assert first.name != final.name
    assert first.metadata()["approval_status"] == final.metadata()["approval_status"] == "UNAPPROVED"
    assert first.metadata()["version"] == final.metadata()["version"] == "v1"
    with pytest.raises(AttributeError):
        first.approval_status = "APPROVED"
    with pytest.raises(TypeError):
        evaluate(pd.DataFrame())
    for kwargs in [{"stage": "both", "name": "pareto"}, {"stage": "stage1", "name": "academic"}]:
        with pytest.raises(ValueError):
            strategy_cls(**kwargs)


@pytest.mark.parametrize("column,bad", [("projected_cumulative_gpa", np.nan),
    ("expected_quality_points", np.inf), ("expected_failed_credits", -1),
    ("expected_plan_gpa", 5), ("failed_balance_penalty", np.inf),
    ("failed_balance_penalty", None), ("scope_applicable", "false")])
def test_invalid_metrics_cannot_enter_total_order(column, bad):
    frame = pd.DataFrame([metric_row("A", 48, .2)])
    frame[column] = bad
    with pytest.raises(ValueError):
        ranked(frame)


@pytest.mark.parametrize("change", ["hash", "duplicate", "flags", "mixed_flags", "disabled_zero", "missing"])
def test_identity_and_disabled_component_contracts_are_validated(change):
    frame = pd.DataFrame([metric_row("A", 48, .2), metric_row("B", 45, .3)])
    if change == "hash":
        frame.loc[0, "plan_id"] = "not-canonical"
    elif change == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]])
    elif change == "flags":
        frame.at[0, "component_active_flags"] = {"failed": "true"}
    elif change == "mixed_flags":
        frame.at[0, "component_active_flags"] = {"failed": True, "withdrawn": True, "total_previous": True}
        frame.at[0, "withdrawn_balance_penalty"] = 0
    elif change == "disabled_zero":
        frame["withdrawn_balance_penalty"] = 0
    else:
        frame = frame.drop(columns="course_tuple")
    with pytest.raises(ValueError):
        ranked(frame)


def test_empty_complete_set_and_input_immutability():
    frame = pd.DataFrame([metric_row("A", 48, .2), metric_row("B", 45, .3)])
    before = frame.copy(deep=True)
    ranked(frame, name="pareto")
    pd.testing.assert_frame_equal(frame, before)
    assert ranked(frame.iloc[:0], name="pareto").empty


def test_imports_and_evaluation_do_not_read_reports_or_load_experiments(tmp_path):
    import subprocess
    import sys
    # A fresh interpreter proves isolation from earlier test imports.
    root = str(__import__("pathlib").Path(__file__).resolve().parents[2])
    script = """
import sys
sys.path.insert(0, sys.argv[1])
def deny_audit_sources(event, args):
    if event == 'open' and 'reports/repeat_withdrawal_analysis' in str(args[0]).replace('\\\\', '/'):
        raise AssertionError('Serving read a diagnostic report')
sys.addaudithook(deny_audit_sources)
import pandas as pd
from src.recommendation.balance_policy import compute_balance_components
from src.recommendation.ranking import RankingStrategy, canonical_plan_identity, rank_evaluation_plans
courses = pd.DataFrame({'course_id': ['A'], 'course_credits': [15], 'candidate_group': ['NEW']})
balance = compute_balance_components(courses, courses, part_semester=1)
identity = canonical_plan_identity(['A'])
metrics = pd.DataFrame([{**balance, 'plan_id': identity.plan_id, 'course_tuple': identity.course_tuple,
    'expected_quality_points': 45, 'expected_failed_credits': .2, 'expected_plan_gpa': 3,
    'projected_cumulative_gpa': 2.2}])
assert len(rank_evaluation_plans(metrics, strategy=RankingStrategy(stage='stage1', name='pareto'))) == 1
assert not any(n.startswith(('src.experiments', 'src.modeling', 'src.diagnostics')) for n in sys.modules)
assert RankingStrategy(stage='stage1', name='pareto').approval_status == 'UNAPPROVED'
"""
    result = subprocess.run([sys.executable, "-c", script, root], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
