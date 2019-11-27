# Copyright 2016, Yahoo Inc.
# Licensed under the terms of the Apache License, Version 2.0. See the LICENSE file associated with the project for terms.

import math
import sys
from functools import partial
from operator import add, floordiv, mul, sub
from pprint import pprint

import pytest

import graphtik.network as network
from graphtik import (
    AbortedException,
    abort_run,
    compose,
    operation,
    optional,
    set_evictions_skipped,
    sideffect,
    vararg,
)
from graphtik.op import Operation


@pytest.fixture(params=[None, "parallel"])
def exemethod(request):
    return request.param


def scream(*args, **kwargs):
    raise AssertionError(
        "Must not have run!\n    args: %s\n  kwargs: %s", (args, kwargs)
    )


def identity(*x):
    return x[0] if len(x) == 1 else x


def filtdict(d, *keys):
    """
    Keep dict items with the given keys

    >>> filtdict({"a": 1, "b": 2}, "b")
    {'b': 2}
    """
    return type(d)(i for i in d.items() if i[0] in keys)


def addall(*a):
    "Same as a + b + ...."
    return sum(a)


def abspow(a, p):
    c = abs(a) ** p
    return c


def test_smoke_test():

    # Sum operation, late-bind compute function
    sum_op1 = operation(name="sum_op1", needs=["a", "b"], provides="sum_ab")(add)

    # sum_op1 is callable
    assert sum_op1(1, 2) == 3

    # Multiply operation, decorate in-place
    @operation(name="mul_op1", needs=["sum_ab", "b"], provides="sum_ab_times_b")
    def mul_op1(a, b):
        return a * b

    # mul_op1 is callable
    assert mul_op1(1, 2) == 2

    # Pow operation
    @operation(
        name="pow_op1", needs="sum_ab", provides=["sum_ab_p1", "sum_ab_p2", "sum_ab_p3"]
    )
    def pow_op1(a, exponent=3):
        return [math.pow(a, y) for y in range(1, exponent + 1)]

    assert pow_op1.compute({"sum_ab": 2}, ["sum_ab_p2"]) == {"sum_ab_p2": 4.0}

    # Partial operation that is bound at a later time
    partial_op = operation(
        name="sum_op2", needs=["sum_ab_p1", "sum_ab_p2"], provides="p1_plus_p2"
    )

    # Bind the partial operation
    sum_op2 = partial_op(add)

    # Sum operation, early-bind compute function
    sum_op_factory = operation(add)

    sum_op3 = sum_op_factory(name="sum_op3", needs=["a", "b"], provides="sum_ab2")

    # sum_op3 is callable
    assert sum_op3(5, 6) == 11

    # compose network
    netop = compose("my network", sum_op1, mul_op1, pow_op1, sum_op2, sum_op3)

    #
    # Running the network
    #

    # get all outputs
    exp = {
        "a": 1,
        "b": 2,
        "p1_plus_p2": 12.0,
        "sum_ab": 3,
        "sum_ab2": 3,
        "sum_ab_p1": 3.0,
        "sum_ab_p2": 9.0,
        "sum_ab_p3": 27.0,
        "sum_ab_times_b": 6,
    }
    assert netop(a=1, b=2) == exp

    # get specific outputs
    exp = {"sum_ab_times_b": 6}
    assert netop.compute({"a": 1, "b": 2}, ["sum_ab_times_b"]) == exp

    # start with inputs already computed
    exp = {"sum_ab_times_b": 2}
    assert netop.compute({"sum_ab": 1, "b": 2}, ["sum_ab_times_b"]) == exp

    with pytest.raises(ValueError, match="Unknown output node"):
        netop.compute({"sum_ab": 1, "b": 2}, "bad_node")
    with pytest.raises(ValueError, match="Unknown output node"):
        netop.compute({"sum_ab": 1, "b": 2}, ["b", "bad_node"])


def test_network_plan_execute():
    def powers_in_trange(a, exponent):
        outputs = []
        for y in range(1, exponent + 1):
            p = math.pow(a, y)
            outputs.append(p)
        return outputs

    sum_op1 = operation(name="sum1", provides=["sum_ab"], needs=["a", "b"])(add)
    mul_op1 = operation(name="mul", provides=["sum_ab_times_b"], needs=["sum_ab", "b"])(
        mul
    )
    pow_op1 = operation(
        name="pow",
        needs=["sum_ab", "exponent"],
        provides=["sum_ab_p1", "sum_ab_p2", "sum_ab_p3"],
    )(powers_in_trange)
    sum_op2 = operation(
        name="sum2", provides=["p1_plus_p2"], needs=["sum_ab_p1", "sum_ab_p2"]
    )(add)

    net = network.Network(sum_op1, mul_op1, pow_op1, sum_op2)
    net.compile()

    #
    # Running the network
    #

    # get all outputs
    exp = {
        "a": 1,
        "b": 2,
        "exponent": 3,
        "p1_plus_p2": 12.0,
        "sum_ab": 3,
        "sum_ab_p1": 3.0,
        "sum_ab_p2": 9.0,
        "sum_ab_p3": 27.0,
        "sum_ab_times_b": 6,
    }

    inputs = {"a": 1, "b": 2, "exponent": 3}
    plan = net.compile(outputs=None, inputs=inputs.keys())
    sol = plan.execute(named_inputs=inputs)
    assert sol == exp

    # get specific outputs
    exp = {"sum_ab_times_b": 6}
    plan = net.compile(outputs=["sum_ab_times_b"], inputs=list(inputs))
    sol = plan.execute(named_inputs=inputs)
    assert sol == exp

    # start with inputs already computed
    inputs = {"sum_ab": 1, "b": 2, "exponent": 3}
    exp = {"sum_ab_times_b": 2}
    plan = net.compile(outputs=["sum_ab_times_b"], inputs=inputs)
    sol = plan.execute(named_inputs={"sum_ab": 1, "b": 2})
    assert sol == exp


def test_network_simple_merge():

    sum_op1 = operation(name="sum_op1", needs=["a", "b"], provides="sum1")(add)
    sum_op2 = operation(name="sum_op2", needs=["a", "b"], provides="sum2")(add)
    sum_op3 = operation(name="sum_op3", needs=["sum1", "c"], provides="sum3")(add)
    net1 = compose("my network 1", sum_op1, sum_op2, sum_op3)

    exp = {"a": 1, "b": 2, "c": 4, "sum1": 3, "sum2": 3, "sum3": 7}
    sol = net1(a=1, b=2, c=4)
    assert sol == exp

    sum_op4 = operation(name="sum_op1", needs=["d", "e"], provides="a")(add)
    sum_op5 = operation(name="sum_op2", needs=["a", "f"], provides="b")(add)

    net2 = compose("my network 2", sum_op4, sum_op5)
    exp = {"a": 3, "b": 7, "d": 1, "e": 2, "f": 4}
    sol = net2(**{"d": 1, "e": 2, "f": 4})
    assert sol == exp

    net3 = compose("merged", net1, net2)
    exp = {
        "a": 3,
        "b": 7,
        "c": 5,
        "d": 1,
        "e": 2,
        "f": 4,
        "sum1": 10,
        "sum2": 10,
        "sum3": 15,
    }
    sol = net3(**{"c": 5, "d": 1, "e": 2, "f": 4})
    assert sol == exp

    assert (
        repr(net3)
        == "NetworkOperation(name='merged', needs=['c', 'd', 'e', 'f'], provides=['sum1', 'sum2', 'sum3', 'a', 'b'])"
    )


def test_network_deep_merge():
    sum_op1 = operation(
        name="sum_op1", needs=[vararg("a"), vararg("b")], provides="sum1"
    )(addall)
    sum_op2 = operation(name="sum_op2", needs=[vararg("a"), "b"], provides="sum2")(
        addall
    )
    sum_op3 = operation(name="sum_op3", needs=["sum1", "c"], provides="sum3")(add)
    net1 = compose("my network 1", sum_op1, sum_op2, sum_op3)
    exp = {"a": 1, "b": 2, "c": 4, "sum1": 3, "sum2": 3, "sum3": 7}
    assert net1(a=1, b=2, c=4) == exp
    assert (
        repr(net1)
        == "NetworkOperation(name='my network 1', needs=[optional('a'), 'b', 'c'], provides=['sum1', 'sum2', 'sum3'])"
    )

    sum_op4 = operation(name="sum_op1", needs=[vararg("a"), "b"], provides="sum1")(
        addall
    )
    sum_op5 = operation(name="sum_op4", needs=["sum1", "b"], provides="sum2")(add)
    net2 = compose("my network 2", sum_op4, sum_op5)
    exp = {"a": 1, "b": 2, "sum1": 3, "sum2": 5}
    assert net2(**{"a": 1, "b": 2}) == exp
    assert (
        repr(net2)
        == "NetworkOperation(name='my network 2', needs=[optional('a'), 'b'], provides=['sum1', 'sum2'])"
    )

    net3 = compose("merged", net1, net2, merge=True)
    exp = {"a": 1, "b": 2, "c": 4, "sum1": 3, "sum2": 3, "sum3": 7}
    assert net3(a=1, b=2, c=4) == exp

    assert (
        repr(net3)
        == "NetworkOperation(name='merged', needs=[optional('a'), 'b', 'c'], provides=['sum2', 'sum1', 'sum3'])"
    )

    ## Reverse ops, change results and `needs` optionality.
    #
    net3 = compose("merged", net2, net1, merge=True)
    exp = {"a": 1, "b": 2, "c": 4, "sum1": 3, "sum2": 5, "sum3": 7}
    assert net3(**{"a": 1, "b": 2, "c": 4}) == exp

    assert (
        repr(net3)
        == "NetworkOperation(name='merged', needs=[optional('a'), 'b', 'c'], provides=['sum1', 'sum2', 'sum3'])"
    )


def test_network_merge_in_doctests():
    graphop = compose(
        "graphop",
        operation(name="mul1", needs=["a", "b"], provides=["ab"])(mul),
        operation(name="sub1", needs=["a", "ab"], provides=["a_minus_ab"])(sub),
        operation(
            name="abspow1", needs=["a_minus_ab"], provides=["abs_a_minus_ab_cubed"]
        )(partial(abspow, p=3)),
    )

    another_graph = compose(
        "another_graph",
        operation(name="mul1", needs=["a", "b"], provides=["ab"])(mul),
        operation(name="mul2", needs=["c", "ab"], provides=["cab"])(mul),
    )
    merged_graph = compose("merged_graph", graphop, another_graph, merge=True)
    assert merged_graph.needs
    assert merged_graph.provides

    assert (
        repr(merged_graph)
        == "NetworkOperation(name='merged_graph', needs=['a', 'b', 'c'], provides=['ab', 'a_minus_ab', 'abs_a_minus_ab_cubed', 'cab'])"
    )


def test_input_based_pruning():
    # Tests to make sure we don't need to pass graph inputs if we're provided
    # with data further downstream in the graph as an input.

    sum1 = 2
    sum2 = 5

    # Set up a net such that if sum1 and sum2 are provided directly, we don't
    # need to provide a and b.
    sum_op1 = operation(name="sum_op1", needs=["a", "b"], provides="sum1")(add)
    sum_op2 = operation(name="sum_op2", needs=["a", "b"], provides="sum2")(add)
    sum_op3 = operation(name="sum_op3", needs=["sum1", "sum2"], provides="sum3")(add)
    net = compose("test_net", sum_op1, sum_op2, sum_op3)

    results = net(**{"sum1": sum1, "sum2": sum2})

    # Make sure we got expected result without having to pass a or b.
    assert "sum3" in results
    assert results["sum3"] == add(sum1, sum2)


def test_output_based_pruning():
    # Tests to make sure we don't need to pass graph inputs if they're not
    # needed to compute the requested outputs.

    c = 2
    d = 3

    # Set up a network such that we don't need to provide a or b if we only
    # request sum3 as output.
    sum_op1 = operation(name="sum_op1", needs=["a", "b"], provides="sum1")(add)
    sum_op2 = operation(name="sum_op2", needs=["c", "d"], provides="sum2")(add)
    sum_op3 = operation(name="sum_op3", needs=["c", "sum2"], provides="sum3")(add)
    net = compose("test_net", sum_op1, sum_op2, sum_op3)

    results = net.compute({"a": 0, "b": 0, "c": c, "d": d}, ["sum3"])

    # Make sure we got expected result without having to pass a or b.
    assert "sum3" in results
    assert results["sum3"] == add(c, add(c, d))


def test_deps_pruning_vs_narrowing():
    # Tests to make sure we don't need to pass graph inputs if they're not
    # needed to compute the requested outputs or of we're provided with
    # inputs that are further downstream in the graph.

    c = 2
    sum2 = 5

    # Set up a network such that we don't need to provide a or b d if we only
    # request sum3 as output and if we provide sum2.
    sum_op1 = operation(name="sum_op1", needs=["a", "b"], provides="sum1")(add)
    sum_op2 = operation(name="sum_op2", needs=["c", "d"], provides="sum2")(add)
    sum_op3 = operation(name="sum_op3", needs=["c", "sum2"], provides="sum3")(add)
    net = compose("test_net", sum_op1, sum_op2, sum_op3)

    results = net.compute({"c": c, "sum2": sum2}, ["sum3"])

    # Make sure we got expected result without having to pass a, b, or d.
    assert "sum3" in results
    assert results["sum3"] == add(c, sum2)

    # Compare with both `narrow()`.
    net = net.narrow(inputs=["c", "sum2"], outputs=["sum3"])
    results = net(c=c, sum2=sum2)

    # Make sure we got expected result without having to pass a, b, or d.
    assert "sum3" in results
    assert results["sum3"] == add(c, sum2)


def test_pruning_raises_for_bad_output():
    # Make sure we get a ValueError during the pruning step if we request an
    # output that doesn't exist.

    # Set up a network that doesn't have the output sum4, which we'll request
    # later.
    sum_op1 = operation(name="sum_op1", needs=["a", "b"], provides="sum1")(add)
    sum_op2 = operation(name="sum_op2", needs=["c", "d"], provides="sum2")(add)
    sum_op3 = operation(name="sum_op3", needs=["c", "sum2"], provides="sum3")(add)
    net = compose("test_net", sum_op1, sum_op2, sum_op3)

    # Request two outputs we can compute and one we can't compute.  Assert
    # that this raises a ValueError.
    with pytest.raises(ValueError) as exinfo:
        net.compute({"a": 1, "b": 2, "c": 3, "d": 4}, ["sum1", "sum3", "sum4"])
    assert exinfo.match("sum4")


def test_pruning_not_overrides_given_intermediate():
    # Test #25: v1.2.4 overwrites intermediate data when no output asked
    pipeline = compose(
        "pipeline",
        operation(name="not run", needs=["a"], provides=["overidden"])(scream),
        operation(name="op", needs=["overidden", "c"], provides=["asked"])(add),
    )

    inputs = {"a": 5, "overidden": 1, "c": 2}
    exp = {"a": 5, "overidden": 1, "c": 2, "asked": 3}
    # v1.2.4.ok
    assert pipeline.compute(inputs, "asked") == filtdict(exp, "asked")
    # FAILs
    # - on v1.2.4 with (overidden, asked): = (5, 7) instead of (1, 3)
    # - on #18(unsatisfied) + #23(ordered-sets) with (overidden, asked) = (5, 7) instead of (1, 3)
    # FIXED on #26
    assert pipeline(**inputs) == exp

    ## Test OVERWITES
    #
    overwrites = {}
    pipeline.set_overwrites_collector(overwrites)
    assert pipeline.compute(inputs, ["asked"]) == filtdict(exp, "asked")
    assert overwrites == {}  # unjust must have been pruned

    overwrites = {}
    pipeline.set_overwrites_collector(overwrites)
    assert pipeline(**inputs) == exp
    assert overwrites == {}  # unjust must have been pruned

    ## Test Parallel
    #
    pipeline.set_execution_method("parallel")
    overwrites = {}
    pipeline.set_overwrites_collector(overwrites)
    assert pipeline.compute(inputs, "asked") == filtdict(exp, "asked")
    assert overwrites == {}  # unjust must have been pruned

    overwrites = {}
    pipeline.set_overwrites_collector(overwrites)
    assert pipeline(**inputs) == exp
    assert overwrites == {}  # unjust must have been pruned


def test_pruning_multiouts_not_override_intermediates1():
    # Test #25: v.1.2.4 overwrites intermediate data when a previous operation
    # must run for its other outputs (outputs asked or not)
    pipeline = compose(
        "graph",
        operation(name="must run", needs=["a"], provides=["overidden", "calced"])(
            lambda x: (x, 2 * x)
        ),
        operation(name="add", needs=["overidden", "calced"], provides=["asked"])(add),
    )

    inputs = {"a": 5, "overidden": 1, "c": 2}
    exp = {"a": 5, "overidden": 1, "calced": 10, "asked": 11}
    # FAILs
    # - on v1.2.4 with (overidden, asked) = (5, 15) instead of (1, 11)
    # - on #18(unsatisfied) + #23(ordered-sets) like v1.2.4.
    # FIXED on #26
    assert pipeline(**{"a": 5, "overidden": 1}) == exp
    # FAILs
    # - on v1.2.4 with KeyError: 'e',
    # - on #18(unsatisfied) + #23(ordered-sets) with empty result.
    # FIXED on #26
    assert pipeline.compute(inputs, "asked") == filtdict(exp, "asked")
    # Plan must contain "overidden" step twice, for pin & evict.
    # Plot it to see, or check https://github.com/huyng/graphtik/pull/1#discussion_r334226396.
    datasteps = [s for s in pipeline.last_plan.steps if s == "overidden"]
    assert len(datasteps) == 2
    assert isinstance(datasteps[0], network._PinInstruction)
    assert isinstance(datasteps[1], network._EvictInstruction)

    ## Test OVERWITES
    #
    overwrites = {}
    pipeline.set_overwrites_collector(overwrites)
    assert pipeline(**{"a": 5, "overidden": 1}) == exp
    assert overwrites == {"overidden": 5}

    overwrites = {}
    pipeline.set_overwrites_collector(overwrites)
    assert pipeline.compute(inputs, "asked") == filtdict(exp, "asked")
    assert overwrites == {"overidden": 5}

    ## Test parallel
    #
    pipeline.set_execution_method("parallel")
    assert pipeline(**{"a": 5, "overidden": 1}) == exp
    assert pipeline.compute(inputs, "asked") == filtdict(exp, "asked")


@pytest.mark.xfail(
    sys.version_info < (3, 6),
    reason="PY3.5- have unstable dicts."
    "E.g. https://travis-ci.org/ankostis/graphtik/jobs/595841023",
)
def test_pruning_multiouts_not_override_intermediates2():
    # Test #25: v.1.2.4 overrides intermediate data when a previous operation
    # must run for its other outputs (outputs asked or not)
    # SPURIOUS FAILS in < PY3.6 due to unordered dicts,
    # eg https://travis-ci.org/ankostis/graphtik/jobs/594813119
    pipeline = compose(
        "pipeline",
        operation(name="must run", needs=["a"], provides=["overidden", "e"])(
            lambda x: (x, 2 * x)
        ),
        operation(name="op1", needs=["overidden", "c"], provides=["d"])(add),
        operation(name="op2", needs=["d", "e"], provides=["asked"])(mul),
    )

    inputs = {"a": 5, "overidden": 1, "c": 2}
    exp = {"a": 5, "overidden": 1, "c": 2, "d": 3, "e": 10, "asked": 30}
    # FAILs
    # - on v1.2.4 with (overidden, asked) = (5, 70) instead of (1, 13)
    # - on #18(unsatisfied) + #23(ordered-sets) like v1.2.4.
    # FIXED on #26
    assert pipeline(**inputs) == exp
    # FAILs
    # - on v1.2.4 with KeyError: 'e',
    # - on #18(unsatisfied) + #23(ordered-sets) with empty result.
    assert pipeline.compute(inputs, "asked") == filtdict(exp, "asked")
    # FIXED on #26

    ## Test OVERWITES
    #
    overwrites = {}
    pipeline.set_overwrites_collector(overwrites)
    assert pipeline(**inputs) == exp
    assert overwrites == {"overidden": 5}

    overwrites = {}
    pipeline.set_overwrites_collector(overwrites)
    assert pipeline.compute(inputs, "asked") == filtdict(exp, "asked")
    assert overwrites == {"overidden": 5}

    ## Test parallel
    #
    pipeline.set_execution_method("parallel")
    assert pipeline(**inputs) == exp
    assert pipeline.compute(inputs, "asked") == filtdict(exp, "asked")


def test_pruning_with_given_intermediate_and_asked_out():
    # Test #24: v1.2.4 does not prune before given intermediate data when
    # outputs not asked, but does so when output asked.
    pipeline = compose(
        "pipeline",
        operation(name="unjustly pruned", needs=["given-1"], provides=["a"])(identity),
        operation(name="shortcuted", needs=["a", "b"], provides=["given-2"])(add),
        operation(name="good_op", needs=["a", "given-2"], provides=["asked"])(add),
    )

    exp = {"given-1": 5, "given-2": 2, "a": 5, "b": 2, "asked": 7}
    # v1.2.4 is ok
    assert pipeline(**{"given-1": 5, "b": 2, "given-2": 2}) == exp
    # FAILS
    # - on v1.2.4 with KeyError: 'a',
    # - on #18 (unsatisfied) with no result.
    # FIXED on #18+#26 (new dag solver).
    assert pipeline.compute(
        {"given-1": 5, "b": 2, "given-2": 2}, "asked"
    ) == filtdict(exp, "asked")

    ## Test OVERWITES
    #
    overwrites = {}
    pipeline.set_overwrites_collector(overwrites)
    assert pipeline(**{"given-1": 5, "b": 2, "given-2": 2}) == exp
    assert overwrites == {}

    overwrites = {}
    pipeline.set_overwrites_collector(overwrites)
    assert pipeline.compute(
        {"given-1": 5, "b": 2, "given-2": 2}, "asked"
    ) == filtdict(exp, "asked")
    assert overwrites == {}

    ## Test parallel
    #  FAIL! in #26!
    #
    pipeline.set_execution_method("parallel")
    assert pipeline(**{"given-1": 5, "b": 2, "given-2": 2}) == exp
    assert pipeline.compute({"given-1": 5, "b": 2, "given-2": 2}, "asked"
    ) == filtdict(exp, "asked")


def test_same_outputs_operations_order():
    # Test operations providing the same output ordered as given.
    op1 = operation(name="add", needs=["a", "b"], provides=["ab"])(add)
    op2 = operation(name="sub", needs=["a", "b"], provides=["ab"])(sub)
    addsub = compose("add_sub", op1, op2)
    subadd = compose("sub_add", op2, op1)

    inp = {"a": 3, "b": 1}
    assert addsub(**inp) == {"a": 3, "b": 1, "ab": 4}
    assert addsub.compute(inp, "ab") == {"ab": 4}
    assert subadd(**inp) == {"a": 3, "b": 1, "ab": 2}
    assert subadd.compute(inp, "ab") == {"ab": 2}

    ## Check it does not duplicate evictions
    assert len(subadd.last_plan.steps) == 4

    ## Add another step to test evictions
    #
    op3 = operation(name="pipe", needs=["ab"], provides=["AB"])(identity)
    addsub = compose("add_sub", op1, op2, op3)
    subadd = compose("sub_add", op2, op1, op3)

    inp = {"a": 3, "b": 1}
    assert addsub(**inp) == {"a": 3, "b": 1, "ab": 4, "AB": 4}
    assert addsub.narrow(outputs="AB")(**inp) == {"AB": 4}
    assert subadd(**inp) == {"a": 3, "b": 1, "ab": 2, "AB": 2}
    assert subadd.compute(inp, "AB") == {"AB": 2}

    assert len(subadd.last_plan.steps) == 6


def test_same_inputs_evictions():
    # Test operations providing the same output ordered as given.
    pipeline = compose(
        "add_sub",
        operation(name="x2", needs=["a", "a"], provides=["2a"])(add),
        operation(name="pipe", needs=["2a"], provides=["@S"])(identity),
    )

    inp = {"a": 3}
    assert pipeline(**inp) == {"a": 3, "2a": 6, "@S": 6}
    assert pipeline.compute(inp, "@S") == {"@S": 6}
    ## Check it does not duplicate evictions
    assert len(pipeline.last_plan.steps) == 4


def test_unsatisfied_operations():
    # Test that operations with partial inputs are culled and not failing.
    pipeline = compose(
        "pipeline",
        operation(name="add", needs=["a", "b1"], provides=["a+b1"])(add),
        operation(name="sub", needs=["a", "b2"], provides=["a-b2"])(sub),
    )

    exp = {"a": 10, "b1": 2, "a+b1": 12}
    assert pipeline(**{"a": 10, "b1": 2}) == exp
    assert pipeline.compute({"a": 10, "b1": 2}, ["a+b1"]) == filtdict(exp, "a+b1")
    assert pipeline.narrow(outputs=["a+b1"])(**{"a": 10, "b1": 2}) == filtdict(exp, "a+b1")

    exp = {"a": 10, "b2": 2, "a-b2": 8}
    assert pipeline(**{"a": 10, "b2": 2}) == exp
    assert pipeline.compute({"a": 10, "b2": 2}, ["a-b2"]) == filtdict(exp, "a-b2")

    ## Test parallel
    #
    pipeline.set_execution_method("parallel")
    exp = {"a": 10, "b1": 2, "a+b1": 12}
    assert pipeline(**{"a": 10, "b1": 2}) == exp
    assert pipeline.compute({"a": 10, "b1": 2}, ["a+b1"]) == filtdict(exp, "a+b1")

    exp = {"a": 10, "b2": 2, "a-b2": 8}
    assert pipeline(**{"a": 10, "b2": 2}) == exp
    assert pipeline.compute({"a": 10, "b2": 2}, ["a-b2"]) == filtdict(exp, "a-b2")


def test_unsatisfied_operations_same_out():
    # Test unsatisfied pairs of operations providing the same output.
    pipeline = compose(
        "pipeline",
        operation(name="mul", needs=["a", "b1"], provides=["ab"])(mul),
        operation(name="div", needs=["a", "b2"], provides=["ab"])(floordiv),
        operation(name="add", needs=["ab", "c"], provides=["ab_plus_c"])(add),
    )

    exp = {"a": 10, "b1": 2, "c": 1, "ab": 20, "ab_plus_c": 21}
    assert pipeline(**{"a": 10, "b1": 2, "c": 1}) == exp
    assert pipeline.compute({"a": 10, "b1": 2, "c": 1}, ["ab_plus_c"]) == filtdict(
        exp, "ab_plus_c"
    )

    exp = {"a": 10, "b2": 2, "c": 1, "ab": 5, "ab_plus_c": 6}
    assert pipeline(**{"a": 10, "b2": 2, "c": 1}) == exp
    assert pipeline.compute({"a": 10, "b2": 2, "c": 1}, ["ab_plus_c"]) == filtdict(
        exp, "ab_plus_c"
    )

    ## Test parallel
    #
    #  FAIL! in #26
    pipeline.set_execution_method("parallel")
    exp = {"a": 10, "b1": 2, "c": 1, "ab": 20, "ab_plus_c": 21}
    assert pipeline(**{"a": 10, "b1": 2, "c": 1}) == exp
    assert pipeline.compute({"a": 10, "b1": 2, "c": 1}, ["ab_plus_c"]) == filtdict(
        exp, "ab_plus_c"
    )
    #
    #  FAIL! in #26
    exp = {"a": 10, "b2": 2, "c": 1, "ab": 5, "ab_plus_c": 6}
    assert pipeline(**{"a": 10, "b2": 2, "c": 1}) == exp
    assert pipeline.compute({"a": 10, "b2": 2, "c": 1}, ["ab_plus_c"]) == filtdict(
        exp, "ab_plus_c"
    )


def test_optional():
    # Test that optional() needs work as expected.

    # Function to add two values plus an optional third value.
    def addplusplus(a, b, c=0):
        return a + b + c

    sum_op = operation(name="sum_op1", needs=["a", "b", optional("c")], provides="sum")(
        addplusplus
    )

    net = compose("test_net", sum_op)

    # Make sure output with optional arg is as expected.
    named_inputs = {"a": 4, "b": 3, "c": 2}
    results = net(**named_inputs)
    assert "sum" in results
    assert results["sum"] == sum(named_inputs.values())

    # Make sure output without optional arg is as expected.
    named_inputs = {"a": 4, "b": 3}
    results = net(**named_inputs)
    assert "sum" in results
    assert results["sum"] == sum(named_inputs.values())


@pytest.mark.parametrize("reverse", [0, 1])
def test_narrow_and_optionality(reverse):
    def add(a=0, b=0):
        return a + b

    op1 = operation(name="op1", needs=[optional("a"), optional("bb")], provides="sum1")(
        add
    )
    op2 = operation(name="op2", needs=["a", optional("bb")], provides="sum2")(add)
    ops = [op1, op2]
    provs = "'sum1', 'sum2'"
    if reversed:
        ops = list(reversed(ops))
        provs = "'sum2', 'sum1'"

    netop = compose("t", *ops)
    assert (
        repr(netop)
        == f"NetworkOperation(name='t', needs=['a', optional('bb')], provides=[{provs}])"
    )

    ## Narrow by `needs`
    #
    netop = compose("t", *ops, needs=["a"])
    assert repr(netop) == f"NetworkOperation(name='t', needs=['a'], provides=[{provs}])"

    netop = compose("t", *ops, needs=["bb"])
    assert (
        repr(netop)
        == "NetworkOperation(name='t', needs=[optional('bb')], provides=['sum1'])"
    )

    ## Narrow by `provides`
    #
    netop = compose("t", *ops, provides="sum1")
    assert (
        repr(netop)
        == "NetworkOperation(name='t', needs=[optional('a'), optional('bb')], provides=['sum1'])"
    )

    netop = compose("t", *ops, provides=["sum2"])
    assert (
        repr(netop)
        == "NetworkOperation(name='t', needs=['a', optional('bb')], provides=['sum2'])"
    )

    ## Narrow by BOTH
    #
    netop = compose("t", *ops, needs="a", provides=["sum1"])
    assert (
        repr(netop)
        == "NetworkOperation(name='t', needs=[optional('a')], provides=['sum1'])"
    )

    with pytest.raises(ValueError, match="Impossible provides.+sum2'"):
        compose("t", *ops, needs="bb", provides=["sum2"])

    ## Narrow by unknown needs
    #
    netop = compose("t", *ops, needs="BAD")
    assert (
        repr(netop)
        == "NetworkOperation(name='t', needs=[optional('BAD')], provides=['sum1'])"
    )


# Function without return value.
def _box_extend(box, *args):
    box.extend([1, 2])


def _box_increment(box):
    for i in range(len(box)):
        box[i] += 1


@pytest.mark.parametrize("bools", range(4))
def test_sideffect_no_real_data(bools):
    reverse = bools >> 0 & 1
    parallel = bools >> 1 & 1

    ops = [
        operation(
            name="extend", needs=["box", sideffect("a")], provides=[sideffect("b")]
        )(_box_extend),
        operation(
            name="increment", needs=["box", sideffect("b")], provides=sideffect("c")
        )(_box_increment),
    ]
    if reverse:
        ops = reversed(ops)
    # Designate `a`, `b` as sideffect inp/out arguments.
    graph = compose("mygraph", *ops)
    if parallel:
        graph.set_execution_method("parallel")

    # Normal data must not match sideffects
    with pytest.raises(ValueError, match="Unknown output node"):
        graph.compute({"box": [0], "a": True}, ["a"])
    with pytest.raises(ValueError, match="Unknown output node"):
        graph.compute({"box": [0], "a": True}, ["b"])

    sol = graph(**{"box": [0], "a": True})
    # Nothing run if no sideffect inputs given.
    assert sol == {
        "box": [0],
        "a": True,
    }  # just the inputs FIXME: must raise if it cannot run!

    # Nothing run if no sideffect inputs given.
    sol = graph.compute({"box": [0], "a": True}, ["box", sideffect("b")])
    assert sol == {}  # FIXME: must raise if it cannot run!

    ## OK INPUT SIDEFFECTS
    #
    # ok, no asked out
    sol = graph.compute({"box": [0], sideffect("a"): True})
    assert sol == {"box": [1, 2, 3], sideffect("a"): True}
    #
    # bad, not asked the out-sideffect
    sol = graph.compute({"box": [0], sideffect("a"): True}, "box")
    assert sol == {}
    #
    # ok, asked the 1st out-sideffect
    sol = graph.compute({"box": [0], sideffect("a"): True}, ["box", sideffect("b")])
    assert sol == {"box": [0, 1, 2]}
    #
    # ok, asked the 2nd out-sideffect
    sol = graph.compute({"box": [0], sideffect("a"): True}, ["box", sideffect("c")])
    assert sol == {"box": [1, 2, 3]}


@pytest.mark.parametrize("bools", range(4))
def test_sideffect_real_input(bools):
    reverse = bools >> 0 & 1
    parallel = bools >> 1 & 1

    ops = [
        operation(name="extend", needs=["box", "a"], provides=[sideffect("b")])(
            _box_extend
        ),
        operation(name="increment", needs=["box", sideffect("b")], provides="c")(
            _box_increment
        ),
    ]
    if reverse:
        ops = reversed(ops)
    # Designate `a`, `b` as sideffect inp/out arguments.
    graph = compose("mygraph", *ops)
    if parallel:
        graph.set_execution_method("parallel")

    assert graph(**{"box": [0], "a": True}) == {"a": True, "box": [1, 2, 3], "c": None}
    assert graph.compute({"box": [0], "a": True}, ["box", "c"]) == {"box": [1, 2, 3], "c": None}


def test_sideffect_steps():
    netop = compose(
        "mygraph",
        operation(
            name="extend", needs=["box", sideffect("a")], provides=[sideffect("b")]
        )(_box_extend),
        operation(
            name="increment", needs=["box", sideffect("b")], provides=sideffect("c")
        )(_box_increment),
    )
    sol = netop.compute({"box": [0], sideffect("a"): True}, ["box", sideffect("c")])
    assert sol == {"box": [1, 2, 3]}
    assert len(netop.last_plan.steps) == 4

    ## Check sideffect links plotted as blue
    #  (assumes color used only for this!).
    dot = netop.net.plot()
    assert "blue" in str(dot)


@pytest.mark.xfail(
    sys.version_info < (3, 6),
    reason="PY3.5- have unstable dicts."
    "E.g. https://travis-ci.org/ankostis/graphtik/jobs/595793872",
)
def test_optional_per_function_with_same_output():
    # Test that the same need can be both optional and not on different operations.
    #
    ## ATTENTION, the selected function is NOT the one with more inputs
    # but the 1st satisfiable function added in the network.

    add_op = operation(name="add", needs=["a", "b"], provides="a+-b")(add)
    sub_op_optional = operation(
        name="sub_opt", needs=["a", optional("b")], provides="a+-b"
    )(lambda a, b=10: a - b)

    # Normal order
    #
    pipeline = compose("partial_optionals", add_op, sub_op_optional)
    #
    named_inputs = {"a": 1, "b": 2}
    assert pipeline(**named_inputs) == {"a": 1, "a+-b": 3, "b": 2}
    assert pipeline.compute(named_inputs, ["a+-b"]) == {"a+-b": 3}
    #
    named_inputs = {"a": 1}
    assert pipeline.compute(named_inputs, recompile=True) == {"a": 1, "a+-b": -9}
    assert pipeline.compute(named_inputs, ["a+-b"]) == {"a+-b": -9}

    # Inverse op order
    #
    pipeline = compose("partial_optionals", sub_op_optional, add_op)
    #
    named_inputs = {"a": 1, "b": 2}
    assert pipeline(**named_inputs) == {"a": 1, "a+-b": -1, "b": 2}
    assert pipeline.compute(named_inputs, ["a+-b"]) == {"a+-b": -1}
    #
    named_inputs = {"a": 1}
    assert pipeline(**named_inputs) == {"a": 1, "a+-b": -9}
    assert pipeline.compute(named_inputs, ["a+-b"]) == {"a+-b": -9}

    # PARALLEL + Normal order
    #
    pipeline = compose("partial_optionals", add_op, sub_op_optional)
    pipeline.set_execution_method("parallel")
    #
    named_inputs = {"a": 1, "b": 2}
    assert pipeline(**named_inputs) == {"a": 1, "a+-b": 3, "b": 2}
    assert pipeline.compute(named_inputs, ["a+-b"]) == {"a+-b": 3}
    #
    named_inputs = {"a": 1}
    assert pipeline(**named_inputs) == {"a": 1, "a+-b": -9}
    assert pipeline.compute(named_inputs, ["a+-b"]) == {"a+-b": -9}

    # PARALLEL + Inverse op order
    #
    pipeline = compose("partial_optionals", sub_op_optional, add_op)
    pipeline.set_execution_method("parallel")
    #
    named_inputs = {"a": 1, "b": 2}
    assert pipeline(**named_inputs) == {"a": 1, "a+-b": -1, "b": 2}
    assert pipeline.compute(named_inputs, ["a+-b"]) == {"a+-b": -1}
    #
    named_inputs = {"a": 1}
    assert pipeline(**named_inputs) == {"a": 1, "a+-b": -9}
    assert pipeline.compute(named_inputs, ["a+-b"]) == {"a+-b": -9}


def test_evicted_optional():
    # Test that _EvictInstructions included for optionals do not raise
    # exceptions when the corresponding input is not prodided.

    # Function to add two values plus an optional third value.
    def addplusplus(a, b, c=0):
        return a + b + c

    # Here, a _EvictInstruction will be inserted for the optional need 'c'.
    sum_op1 = operation(
        name="sum_op1", needs=["a", "b", optional("c")], provides="sum1"
    )(addplusplus)
    sum_op2 = operation(name="sum_op2", needs=["sum1", "sum1"], provides="sum2")(add)
    net = compose("test_net", sum_op1, sum_op2)

    # _EvictInstructions are used only when a subset of outputs are requested.
    results = net.compute({"a": 4, "b": 3}, ["sum2"])
    assert "sum2" in results


def test_evict_instructions_vary_with_inputs():
    # Check #21: _EvictInstructions positions vary when inputs change.
    def count_evictions(steps):
        return sum(isinstance(n, network._EvictInstruction) for n in steps)

    pipeline = compose(
        "pipeline",
        operation(name="a free without b", needs=["a"], provides=["aa"])(identity),
        operation(name="satisfiable", needs=["a", "b"], provides=["ab"])(add),
        operation(name="optional ab", needs=["aa", optional("ab")], provides=["asked"])(
            lambda a, ab=10: a + ab
        ),
    )

    inp = {"a": 2, "b": 3}
    exp = inp.copy()
    exp.update({"aa": 2, "ab": 5, "asked": 7})
    res = pipeline(**inp)
    assert res == exp  # ok
    steps11 = pipeline.net.compile(inp).steps
    res = pipeline.compute(inp, ["asked"])
    assert res == filtdict(exp, "asked")  # ok
    steps12 = pipeline.net.compile(inp, ["asked"]).steps

    inp = {"a": 2}
    exp = inp.copy()
    exp.update({"aa": 2, "asked": 12})
    res = pipeline(**inp)
    assert res == exp  # ok
    steps21 = pipeline.net.compile(inp).steps
    res = pipeline.compute(inp, ["asked"])
    assert res == filtdict(exp, "asked")  # ok
    steps22 = pipeline.net.compile(inp, ["asked"]).steps

    # When no outs, no evict-instructions.
    assert steps11 != steps12
    assert count_evictions(steps11) == 0
    assert steps21 != steps22
    assert count_evictions(steps21) == 0

    # Check steps vary with inputs
    #
    # FAILs in v1.2.4 + #18, PASS in #26
    assert steps11 != steps21

    # Check evicts vary with inputs
    #
    # FAILs in v1.2.4 + #18, PASS in #26
    assert count_evictions(steps12) != count_evictions(steps22)


def test_skip_eviction_flag():
    graph = compose(
        "graph",
        operation(name="add1", needs=["a", "b"], provides=["ab"])(add),
        operation(name="add2", needs=["a", "ab"], provides=["aab"])(add),
    )
    set_evictions_skipped(True)
    try:
        exp = {"a": 1, "b": 3, "ab": 4, "aab": 5}
        assert graph.compute({"a": 1, "b": 3}, "aab") == exp
    finally:
        set_evictions_skipped(False)


def test_multithreading_plan_execution():
    # From Huygn's test-code given in yahoo/graphkit#31
    from multiprocessing.dummy import Pool
    from graphtik import compose, operation

    # Compose the mul, sub, and abspow operations into a computation graph.
    graph = compose(
        "graph",
        operation(name="mul1", needs=["a", "b"], provides=["ab"])(mul),
        operation(name="sub1", needs=["a", "ab"], provides=["a_minus_ab"])(sub),
        operation(
            name="abspow1", needs=["a_minus_ab"], provides=["abs_a_minus_ab_cubed"]
        )(partial(abspow, p=3)),
    )

    pool = Pool(10)
    graph.set_execution_method("parallel")
    pool.map(
        lambda i: graph.compute({"a": 2, "b": 5}, ["a_minus_ab", "abs_a_minus_ab_cubed"]),
        range(100),
    )


@pytest.mark.slow
def test_parallel_execution():
    import time

    delay = 0.5

    def fn(x):
        time.sleep(delay)
        print("fn %s" % (time.time() - t0))
        return 1 + x

    def fn2(a, b):
        time.sleep(delay)
        print("fn2 %s" % (time.time() - t0))
        return a + b

    def fn3(z, k=1):
        time.sleep(delay)
        print("fn3 %s" % (time.time() - t0))
        return z + k

    pipeline = compose(
        "l",
        # the following should execute in parallel under threaded execution mode
        operation(name="a", needs="x", provides="ao")(fn),
        operation(name="b", needs="x", provides="bo")(fn),
        # this should execute after a and b have finished
        operation(name="c", needs=["ao", "bo"], provides="co")(fn2),
        operation(name="d", needs=["ao", optional("k")], provides="do")(fn3),
        operation(name="e", needs=["ao", "bo"], provides="eo")(fn2),
        operation(name="f", needs="eo", provides="fo")(fn),
        operation(name="g", needs="fo", provides="go")(fn),
        merge=True,
    )

    t0 = time.time()
    pipeline.set_execution_method("parallel")
    result_threaded = pipeline.compute({"x": 10}, ["co", "go", "do"])
    print("threaded result")
    print(result_threaded)

    t0 = time.time()
    pipeline.set_execution_method(None)
    result_sequential = pipeline.compute({"x": 10}, ["co", "go", "do"])
    print("sequential result")
    print(result_sequential)

    # make sure results are the same using either method
    assert result_sequential == result_threaded


@pytest.mark.slow
def test_multi_threading():
    import time
    import random
    from multiprocessing.dummy import Pool

    def op_a(a, b):
        time.sleep(random.random() * 0.02)
        return a + b

    def op_b(c, b):
        time.sleep(random.random() * 0.02)
        return c + b

    def op_c(a, b):
        time.sleep(random.random() * 0.02)
        return a * b

    pipeline = compose(
        "pipeline",
        operation(name="op_a", needs=["a", "b"], provides="c")(op_a),
        operation(name="op_b", needs=["c", "b"], provides="d")(op_b),
        operation(name="op_c", needs=["a", "b"], provides="e")(op_c),
        merge=True,
    )

    def infer(i):
        # data = open("616039-bradpitt.jpg").read()
        outputs = ["c", "d", "e"]
        results = pipeline.compute({"a": 1, "b": 2}, outputs)
        assert tuple(sorted(results.keys())) == tuple(sorted(outputs)), (
            outputs,
            results,
        )
        return results

    N = 33
    for i in range(13, 61):
        pool = Pool(i)
        pool.map(infer, range(N))
        pool.close()


@pytest.mark.parametrize("bools", range(4))
def test_compose_another_network(bools):
    # Code from `compose.rst` examples

    parallel1 = bools >> 0 & 1
    parallel2 = bools >> 1 & 1

    graphop = compose(
        "graphop",
        operation(name="mul1", needs=["a", "b"], provides=["ab"])(mul),
        operation(name="sub1", needs=["a", "ab"], provides=["a_minus_ab"])(sub),
        operation(
            name="abspow1", needs=["a_minus_ab"], provides=["abs_a_minus_ab_cubed"]
        )(partial(abspow, p=3)),
    )
    if parallel1:
        graphop.set_execution_method("parallel")

    assert graphop(a_minus_ab=-8) == {
        "a_minus_ab": -8,
        "abs_a_minus_ab_cubed": 512,
    }

    bigger_graph = compose(
        "bigger_graph",
        graphop,
        operation(
            name="sub2", needs=["a_minus_ab", "c"], provides="a_minus_ab_minus_c"
        )(sub),
    )
    if parallel2:
        bigger_graph.set_execution_method("parallel")

    sol = bigger_graph.compute({"a": 2, "b": 5, "c": 5}, ["a_minus_ab_minus_c"])
    assert sol == {"a_minus_ab_minus_c": -13}


def test_abort(exemethod):
    pipeline = compose(
        "pipeline",
        operation(name="A", needs=["a"], provides=["b"])(identity),
        operation(name="B", needs=["b"], provides=["c"])(lambda x: abort_run()),
        operation(name="C", needs=["c"], provides=["d"])(identity),
    )
    pipeline.set_execution_method(exemethod)
    with pytest.raises(AbortedException) as exinfo:
        pipeline(a=1)
    assert exinfo.value.jetsam["solution"] == {"a": 1, "b": 1, "c": None}
    executed = {op.name: val for op, val in exinfo.value.args[0].items()}
    assert executed == {"A": True, "B": True, "C": False}

    pipeline = compose(
        "pipeline", operation(name="A", needs=["a"], provides=["b"])(identity)
    )
    pipeline.set_execution_method(exemethod)
    assert pipeline.compute({"a": 1}) == {"a": 1, "b": 1}
