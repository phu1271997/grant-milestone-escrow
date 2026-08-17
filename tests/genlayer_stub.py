"""An in-process stand-in for the `genlayer` runtime.

`gltest --network studionet` exercises the real thing, but it needs a funded
account, live inference and working network, which makes it a poor fit for the
tight loop you actually develop in. This module lets the *same contract source*
run under plain pytest in milliseconds, with the parts that matter modelled
honestly rather than stubbed away:

* **Consensus really runs.** `run_nondet_default` executes the leader function,
  wraps the result in a `Return`, and then calls the validator — which runs the
  observation a second time. A validator that would disagree on chain raises
  `ConsensusDisagreement` here. That is the single most valuable thing to be
  able to test offline, because a validator that agrees too readily is invisible
  in a happy-path demo.
* **Cross-contract calls really dispatch.** Deployed contracts live in an
  address registry, so `gl.get_contract_at(addr).emit().record_settlement(...)`
  lands in the real `BuilderReputation` method and its guards run.
* **Value transfers really move.** A ledger tracks balances, so an escrow that
  pays out twice, or pays more than it holds, shows up as a wrong number.

What is *not* modelled: gas, finality, appeals at the consensus layer, and
validator diversity beyond "run the same function again". Those need studionet.
"""

import json
import sys
import types


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


class _Alias:
    """Stands in for a parameterised generic such as `TreeMap[str, Grant]`."""

    def __init__(self, origin, args):
        self.__origin__ = origin
        self.__args__ = args if isinstance(args, tuple) else (args,)

    def __call__(self, *args, **kwargs):
        return self.__origin__(*args, **kwargs)

    def __repr__(self):
        return f"{self.__origin__.__name__}[{self.__args__}]"


class SizedInt(int):
    """Base for the fixed-width integer types; behaves as a plain int."""

    def __repr__(self):
        return f"{type(self).__name__}({int(self)})"


class u8(SizedInt):
    pass


class u16(SizedInt):
    pass


class u32(SizedInt):
    pass


class u64(SizedInt):
    pass


class u256(SizedInt):
    pass


class i256(SizedInt):
    pass


class bigint(SizedInt):
    pass


class TreeMap(dict):
    """Ordered mapping stand-in for the GenVM storage map."""

    def __class_getitem__(cls, item):
        return _Alias(cls, item)


class DynArray(list):
    """Growable array stand-in for the GenVM storage array."""

    def __class_getitem__(cls, item):
        return _Alias(cls, item)


class Address:
    """Minimal address wrapper exposing the `as_hex` accessor contracts use."""

    def __init__(self, value):
        if isinstance(value, Address):
            value = value.as_hex
        if not isinstance(value, str):
            raise TypeError("Address requires a hex string")
        clean = value.strip().lower()
        if len(clean) != 42 or not clean.startswith("0x"):
            raise ValueError(f"bad address: {value}")
        self.as_hex = clean

    def __eq__(self, other):
        return isinstance(other, Address) and other.as_hex == self.as_hex

    def __hash__(self):
        return hash(self.as_hex)

    def __str__(self):
        return self.as_hex

    def __repr__(self):
        return f"Address({self.as_hex})"


def allow_storage(cls):
    """No-op marker; on chain it makes a dataclass storable."""
    return cls


# ---------------------------------------------------------------------------
# VM errors and consensus
# ---------------------------------------------------------------------------


class UserError(Exception):
    """Contract-raised error that rolls the transaction back."""

    def __init__(self, data=""):
        super().__init__(str(data))
        self.data = data


class VMError(Exception):
    pass


class Return:
    """Wrapper the VM puts around a leader result before validation."""

    def __init__(self, calldata):
        self.calldata = calldata


class ConsensusDisagreement(Exception):
    """Raised when the validator rejects the leader's result.

    On chain this terminates the transaction. Surfacing it as a distinct
    exception is what lets a test assert 'these two readings must NOT both be
    accepted', which is the property the whole design rests on.
    """


class Rollback(Exception):
    pass


# ---------------------------------------------------------------------------
# Mutable execution context
# ---------------------------------------------------------------------------


class World:
    """Everything a test can steer: identities, money, network, inference."""

    def __init__(self):
        self.sender = Address("0x" + "11" * 20)
        self.value = 0
        self.balances = {}
        self.contracts = {}
        self.http_handler = None
        self.render_handler = None
        self.prompt_handler = None
        self.http_log = []
        self.render_log = []
        self.prompt_log = []
        self.transfers = []
        self._next_address = 1

    # -- identities ---------------------------------------------------

    def new_address(self) -> str:
        self._next_address += 1
        return "0x" + f"{self._next_address:040x}"

    def balance_of(self, addr) -> int:
        key = addr.as_hex if isinstance(addr, Address) else str(addr).lower()
        return self.balances.get(key, 0)

    def credit(self, addr, amount: int) -> None:
        key = addr.as_hex if isinstance(addr, Address) else str(addr).lower()
        self.balances[key] = self.balances.get(key, 0) + amount

    # -- contract registry --------------------------------------------

    def register(self, instance) -> str:
        address = self.new_address()
        self.contracts[address] = instance
        instance.__gl_address__ = address
        return address


WORLD = World()


def reset_world() -> World:
    """Start a fresh world. Called by the pytest fixture between tests."""
    global WORLD
    WORLD = World()
    _rebind_message()
    return WORLD


# ---------------------------------------------------------------------------
# gl namespace
# ---------------------------------------------------------------------------


class _Public:
    class _Write:
        def __call__(self, fn):
            return fn

        def payable(self, fn):
            return fn

        def min_gas(self, **kwargs):
            return self

    def __init__(self):
        self.write = _Public._Write()

    @staticmethod
    def view(fn):
        return fn


class _Private:
    @staticmethod
    def view(fn):
        return fn

    @staticmethod
    def write(fn):
        return fn


class _Message(types.SimpleNamespace):
    """`gl.message` reads through to the live world on every access."""

    @property
    def sender_address(self):
        return WORLD.sender

    @property
    def value(self):
        return WORLD.value


_MESSAGE = _Message()


def _rebind_message():
    gl.message = _MESSAGE


class _Web:
    @staticmethod
    def get(url, *, headers=None, sign=False):
        WORLD.http_log.append(url)
        if WORLD.http_handler is None:
            raise RuntimeError(f"no http handler installed; contract fetched {url}")
        return WORLD.http_handler(url, headers or {})

    @staticmethod
    def render(url, *, mode="text", wait_after_loaded=None):
        WORLD.render_log.append(url)
        if WORLD.render_handler is None:
            raise RuntimeError(f"no render handler installed; contract rendered {url}")
        return WORLD.render_handler(url, mode)


class Response:
    """Shape-compatible with `gl.nondet.web.Response`."""

    def __init__(self, status, body=b"", headers=None):
        self.status = status
        self.status_code = status
        self.body = body if isinstance(body, (bytes, bytearray)) else str(body).encode("utf-8")
        self.headers = headers or {}


def json_response(payload, status=200) -> Response:
    """Convenience builder for a JSON API reply."""
    return Response(status, json.dumps(payload).encode("utf-8"))


class _Nondet:
    web = _Web()

    @staticmethod
    def exec_prompt(prompt, *, response_format="text", images=None, image=None):
        WORLD.prompt_log.append(prompt)
        if WORLD.prompt_handler is None:
            raise RuntimeError("no prompt handler installed")
        return WORLD.prompt_handler(prompt, response_format)


class _Vm:
    UserError = UserError
    VMError = VMError
    Return = Return

    @staticmethod
    def run_nondet_default(leader_fn, validator_fn, **kwargs):
        """Execute leader, then genuinely run the validator against it."""
        leader_result = leader_fn()
        if not validator_fn(Return(leader_result)):
            raise ConsensusDisagreement("validator rejected the leader result")
        return leader_result

    @staticmethod
    def run_nondet(leader_fn, validator_fn):
        return _Vm.run_nondet_default(leader_fn, validator_fn)

    @staticmethod
    def run_nondet_unsafe(leader_fn, validator_fn):
        return _Vm.run_nondet_default(leader_fn, validator_fn)

    @staticmethod
    def trace(*args, **kwargs):
        return None


class _EqPrinciple:
    @staticmethod
    def strict_eq(fn):
        return fn()

    @staticmethod
    def prompt_comparative(fn, principle):
        return fn()

    @staticmethod
    def prompt_non_comparative(fn, *, task, criteria):
        return fn()


class _ContractProxy:
    """Dispatches view/write calls to another registered contract instance.

    Sender and value are swapped for the duration of the call, exactly as a real
    internal message would, so the callee's `NOT_AUTHORIZED_WRITER` style guards
    are actually exercised instead of being bypassed by shared globals.
    """

    def __init__(self, address: str):
        self.address = address

    def _target(self):
        target = WORLD.contracts.get(self.address)
        if target is None:
            raise UserError(f"no contract at {self.address}")
        return target

    def view(self, **kwargs):
        return _CallScope(self._target(), self.address, value=0)

    def emit(self, *, value=0, on="finalized", **kwargs):
        return _CallScope(self._target(), self.address, value=int(value))

    def emit_transfer(self, value=0, *, on="finalized", **kwargs):
        amount = int(value)
        if amount <= 0:
            raise ValueError("emit_transfer requires a positive value")
        # Debit the paying contract as well as crediting the recipient, so a
        # double payout or an overspend shows up as a negative balance rather
        # than quietly succeeding.
        payer = _current_contract_address()
        if payer:
            WORLD.credit(payer, -amount)
        WORLD.credit(self.address, amount)
        WORLD.transfers.append((self.address, amount))


class _CallScope:
    """Binds an internal-message sender around each forwarded method call."""

    def __init__(self, target, address, value):
        self._target = target
        self._address = address
        self._value = value

    def __getattr__(self, name):
        method = getattr(self._target, name)

        def invoke(*args, **kwargs):
            previous_sender, previous_value = WORLD.sender, WORLD.value
            # An internal message is sent by the calling *contract*, not by the
            # end user, so the callee's authorisation guards see the escrow.
            caller = _current_contract_address()
            WORLD.sender = Address(caller) if caller else previous_sender
            WORLD.value = self._value
            try:
                return method(*args, **kwargs)
            finally:
                WORLD.sender, WORLD.value = previous_sender, previous_value

        return invoke


_CALL_STACK = []


def _current_contract_address():
    return _CALL_STACK[-1] if _CALL_STACK else None


def get_contract_at(address):
    hex_address = address.as_hex if isinstance(address, Address) else str(address).lower()
    return _ContractProxy(hex_address)


def contract_interface(cls):
    """Return a factory that builds a proxy for the given address."""

    def factory(address):
        return get_contract_at(address)

    factory.__name__ = getattr(cls, "__name__", "Interface")
    return factory


class _ContractBase:
    """Base class that pre-initialises annotated storage fields.

    The GenVM auto-creates `TreeMap` and `DynArray` fields, which is why
    contracts must not assign them in `__init__`. That behaviour is reproduced
    here so a contract which *did* assign them would still pass locally and then
    fail on chain — the local run must not be more forgiving than the real one.
    """

    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls)
        for klass in reversed(cls.__mro__):
            for name, annotation in getattr(klass, "__annotations__", {}).items():
                origin = getattr(annotation, "__origin__", annotation)
                if origin is TreeMap:
                    setattr(obj, name, TreeMap())
                elif origin is DynArray:
                    setattr(obj, name, DynArray())
        return obj


class _Storage:
    allow = staticmethod(allow_storage)
    allow_storage = staticmethod(allow_storage)
    TreeMap = TreeMap
    DynArray = DynArray

    @staticmethod
    def inmem_allocate(t, *args, **kwargs):
        origin = getattr(t, "__origin__", t)
        return origin(*args, **kwargs)


gl = types.SimpleNamespace(
    Contract=_ContractBase,
    public=_Public(),
    private=_Private(),
    vm=_Vm(),
    nondet=_Nondet(),
    eq_principle=_EqPrinciple(),
    storage=_Storage(),
    message=_MESSAGE,
    get_contract_at=get_contract_at,
    contract_interface=contract_interface,
    Address=Address,
    TreeMap=TreeMap,
    DynArray=DynArray,
    IS_IN_VM=True,
)


# ---------------------------------------------------------------------------
# Module installation and contract loading
# ---------------------------------------------------------------------------


def install() -> None:
    """Publish this shim as the importable `genlayer` module."""
    module = types.ModuleType("genlayer")
    for name in (
        "gl",
        "Address",
        "TreeMap",
        "DynArray",
        "allow_storage",
        "u8",
        "u16",
        "u32",
        "u64",
        "u256",
        "i256",
        "bigint",
        "Return",
        "UserError",
    ):
        setattr(module, name, globals()[name])
    sys.modules["genlayer"] = module


def load_contract(path, module_name):
    """Import a contract file as a module with the shim already in place."""
    import importlib.util

    install()
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def deploy(module, sender: str, *args, **kwargs):
    """Instantiate a contract as `sender` and register it at a fresh address."""
    previous_sender, previous_value = WORLD.sender, WORLD.value
    WORLD.sender = Address(sender)
    WORLD.value = 0
    try:
        instance = module.Contract(*args, **kwargs)
    finally:
        WORLD.sender, WORLD.value = previous_sender, previous_value
    WORLD.register(instance)
    return instance


def call(instance, method_name: str, *args, sender: str = None, value: int = 0, **kwargs):
    """Invoke a contract method with an explicit sender and attached value.

    Mirrors gltest's `.connect(acct).method(args=[...]).transact(value=X)`: the
    caller identity and the transferred value are part of the call, never
    ambient state a test can forget to set.
    """
    previous_sender, previous_value = WORLD.sender, WORLD.value
    if sender is not None:
        WORLD.sender = Address(sender)
    WORLD.value = int(value)
    if value:
        WORLD.credit(getattr(instance, "__gl_address__", "0x" + "0" * 40), int(value))
    _CALL_STACK.append(getattr(instance, "__gl_address__", None))
    try:
        return getattr(instance, method_name)(*args, **kwargs)
    finally:
        _CALL_STACK.pop()
        WORLD.sender, WORLD.value = previous_sender, previous_value


def view(instance, method_name: str, *args, **kwargs):
    """Invoke a read-only method and JSON-decode its response."""
    raw = getattr(instance, method_name)(*args, **kwargs)
    return json.loads(raw) if isinstance(raw, str) else raw

