"""
Memory expansion tests for DATACOPY
"""
from typing import Mapping, Tuple

import pytest

from ethereum_test_tools import (
    Account,
    Alloc,
    Bytecode,
    Environment,
    StateTestFiller,
    Storage,
    Transaction,
)
from ethereum_test_tools.common.base_types import Address
from ethereum_test_tools.common.helpers import cost_memory_bytes
from ethereum_test_tools.eof.v1 import Container, Section
from ethereum_test_tools.vm.opcode import Opcodes as Op

from .. import EOF_FORK_NAME

REFERENCE_SPEC_GIT_PATH = "EIPS/eip-7480.md"
REFERENCE_SPEC_VERSION = "3ee1334ef110420685f1c8ed63e80f9e1766c251"

pytestmark = pytest.mark.valid_from(EOF_FORK_NAME)


@pytest.fixture
def callee_bytecode(dest: int, src: int, length: int, data_section: bytes) -> Container:
    """
    Callee performs a single datacopy operation and then returns.
    """
    bytecode = Bytecode()

    # Copy the initial memory
    bytecode += Op.CALLDATACOPY(0x00, 0x00, Op.CALLDATASIZE())

    # Pushes for the return operation
    bytecode += Op.PUSH1(0x00) + Op.PUSH1(0x00)

    # Perform the datacopy operation
    bytecode += Op.DATACOPY(dest, src, length)

    bytecode += Op.RETURN

    return Container(sections=[Section.Code(code=bytecode), Section.Data(data=data_section)])


@pytest.fixture
def subcall_exact_cost(
    initial_memory: bytes,
    dest: int,
    length: int,
) -> int:
    """
    Returns the exact cost of the subcall, based on the initial memory and the length of the copy.
    """
    datacopy_cost = 3
    datacopy_cost += 3 * ((length + 31) // 32)
    if length > 0 and dest + length > len(initial_memory):
        datacopy_cost += cost_memory_bytes(dest + length, len(initial_memory))

    calldatacopy_cost = 3
    calldatacopy_cost += 3 * ((len(initial_memory) + 31) // 32)
    calldatacopy_cost += cost_memory_bytes(len(initial_memory), 0)

    pushes_cost = 3 * 7
    calldatasize_cost = 2
    return datacopy_cost + calldatacopy_cost + pushes_cost + calldatasize_cost


@pytest.fixture
def bytecode_storage(
    subcall_exact_cost: int,
    successful: bool,
    memory_expansion_address: Address,
) -> Tuple[Bytecode, Storage.StorageDictType]:
    """
    Prepares the bytecode and storage for the test, based on the expected result of the subcall
    (whether it succeeds or fails depending on the length of the memory expansion).
    """
    bytecode = Bytecode()
    storage = {}

    # Pass on the calldata
    bytecode += Op.CALLDATACOPY(0x00, 0x00, Op.CALLDATASIZE())

    subcall_gas = subcall_exact_cost if successful else subcall_exact_cost - 1

    # Perform the subcall and store a one in the result location
    bytecode += Op.SSTORE(
        Op.CALL(subcall_gas, memory_expansion_address, 0, 0, Op.CALLDATASIZE(), 0, 0), 1
    )
    storage[int(successful)] = 1

    return (bytecode, storage)


@pytest.fixture
def tx_max_fee_per_gas() -> int:  # noqa: D103
    return 7


@pytest.fixture
def block_gas_limit() -> int:  # noqa: D103
    return 100_000_000


@pytest.fixture
def tx_gas_limit(  # noqa: D103
    subcall_exact_cost: int,
    block_gas_limit: int,
) -> int:
    return min(max(500_000, subcall_exact_cost * 2), block_gas_limit)


@pytest.fixture
def env(  # noqa: D103
    block_gas_limit: int,
) -> Environment:
    return Environment(gas_limit=block_gas_limit)


@pytest.fixture
def caller_address(  # noqa: D103
    pre: Alloc, bytecode_storage: Tuple[bytes, Storage.StorageDictType]
) -> Address:
    return pre.deploy_contract(code=bytecode_storage[0])


@pytest.fixture
def memory_expansion_address(pre: Alloc, callee_bytecode: bytes) -> Address:  # noqa: D103
    return pre.deploy_contract(code=callee_bytecode)


@pytest.fixture
def sender(pre: Alloc, tx_max_fee_per_gas: int, tx_gas_limit: int) -> Address:  # noqa: D103
    return pre.fund_eoa(tx_max_fee_per_gas * tx_gas_limit)


@pytest.fixture
def tx(  # noqa: D103
    sender: Address,
    caller_address: Address,
    initial_memory: bytes,
    tx_max_fee_per_gas: int,
    tx_gas_limit: int,
) -> Transaction:
    return Transaction(
        sender=sender,
        to=caller_address,
        data=initial_memory,
        gas_limit=tx_gas_limit,
        max_fee_per_gas=tx_max_fee_per_gas,
        max_priority_fee_per_gas=0,
    )


@pytest.fixture
def post(  # noqa: D103
    caller_address: Address, bytecode_storage: Tuple[bytes, Storage.StorageDictType]
) -> Mapping:
    return {
        caller_address: Account(storage=bytecode_storage[1]),
    }


@pytest.mark.parametrize(
    "dest,src,length",
    [
        (0x00, 0x00, 0x01),
        (0x100, 0x00, 0x01),
        (0x1F, 0x00, 0x01),
        (0x20, 0x00, 0x01),
        (0x1000, 0x00, 0x01),
        (0x1000, 0x00, 0x40),
        (0x00, 0x00, 0x00),
        (2**256 - 1, 0x00, 0x00),
        (0x00, 2**256 - 1, 0x00),
        (2**256 - 1, 2**256 - 1, 0x00),
    ],
    ids=[
        "single_byte_expansion",
        "single_byte_expansion_2",
        "single_byte_expansion_word_boundary",
        "single_byte_expansion_word_boundary_2",
        "multi_word_expansion",
        "multi_word_expansion_2",
        "zero_length_expansion",
        "huge_dest_zero_length",
        "huge_src_zero_length",
        "huge_dest_huge_src_zero_length",
    ],
)
@pytest.mark.parametrize("successful", [True, False])
@pytest.mark.parametrize(
    "initial_memory",
    [
        bytes(range(0x00, 0x100)),
        bytes(),
    ],
    ids=[
        "from_existent_memory",
        "from_empty_memory",
    ],
)
@pytest.mark.parametrize(
    "data_section",
    [
        bytes(),
        b"\xfc",
        bytes(range(0x00, 0x20)),
        bytes(range(0x00, 0x100)),
    ],
    ids=["empty_data_section", "byte_data_section", "word_data_section", "large_data_section"],
)
def test_datacopy_memory_expansion(
    state_test: StateTestFiller,
    env: Environment,
    pre: Alloc,
    post: Mapping[str, Account],
    tx: Transaction,
):
    """
    Perform DATACOPY operations that expand the memory, and verify the gas it costs to do so.
    """
    state_test(
        env=env,
        pre=pre,
        post=post,
        tx=tx,
    )


@pytest.mark.parametrize(
    "dest,src,length",
    [
        (2**256 - 1, 0x00, 0x01),
        (2**256 - 2, 0x00, 0x01),
        (2**255 - 1, 0x00, 0x01),
        (0x00, 0x00, 2**256 - 1),
        (0x00, 0x00, 2**256 - 2),
        (0x00, 0x00, 2**255 - 1),
    ],
    ids=[
        "max_dest_single_byte_expansion",
        "max_dest_minus_one_single_byte_expansion",
        "half_max_dest_single_byte_expansion",
        "max_length_expansion",
        "max_length_minus_one_expansion",
        "half_max_length_expansion",
    ],
)
@pytest.mark.parametrize(
    "subcall_exact_cost",
    [2**128 - 1],
    ids=[""],
)  # Limit subcall gas, otherwise it would be impossibly large
@pytest.mark.parametrize("successful", [False])
@pytest.mark.parametrize(
    "initial_memory",
    [
        bytes(range(0x00, 0x100)),
        bytes(),
    ],
    ids=[
        "from_existent_memory",
        "from_empty_memory",
    ],
)
@pytest.mark.parametrize(
    "data_section",
    [
        bytes(),
        b"\xfc",
        bytes(range(0x00, 0x20)),
        bytes(range(0x00, 0x100)),
    ],
    ids=["empty_data_section", "byte_data_section", "word_data_section", "large_data_section"],
)
def test_datacopy_huge_memory_expansion(
    state_test: StateTestFiller,
    env: Environment,
    pre: Mapping[str, Account],
    post: Mapping[str, Account],
    tx: Transaction,
):
    """
    Perform DATACOPY operations that expand the memory by huge amounts, and verify that it
    correctly runs out of gas.
    """
    state_test(
        env=env,
        pre=pre,
        post=post,
        tx=tx,
    )
