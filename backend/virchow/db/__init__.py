import sys
import types

class MockObject:
    def __init__(self, name="Mock"): 
        self._name = name
    def __getattr__(self, name): 
        return MockObject(name)
    def __call__(self, *args, **kwargs): 
        return self
    def __getitem__(self, key): 
        # Return a dict for 'metadata' if Pydantic expects it
        if key == 'metadata': return {}
        return self
    def __setitem__(self, key, value): 
        pass
    def __iter__(self): 
        return iter([])
    def __repr__(self): 
        return self._name
    def __bool__(self): 
        return True
    def __hash__(self):
        return hash(self._name)
    def __eq__(self, other):
        return isinstance(other, MockObject) and self._name == other._name

class MockModule(types.ModuleType):
    def __getattr__(self, name):
        return MockObject(name)

def shim_module(name):
    if name not in sys.modules:
        sys.modules[name] = MockModule(name)

# Manually shim common modules
for m in [
    "virchow.db.pat", "virchow.db.api_key", "virchow.db.chat", 
    "virchow.db.document", "virchow.db.connector", "virchow.db.llm", 
    "virchow.db.persona", "virchow.db.prompt", "virchow.db.user", "virchow.db.tag",
    "virchow.db.engine.async_sql_engine", "virchow.db.users", "virchow.db.assistant",
    "virchow.db.group", "virchow.db.index_attempt"
]:
    shim_module(m)
