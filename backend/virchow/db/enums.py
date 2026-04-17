from enum import Enum

class MockObject:
    def __init__(self, name="Mock"): 
        self._name = name
    def __getattr__(self, name): 
        return MockObject(name)
    def __call__(self, *args, **kwargs): 
        return self
    def __getitem__(self, key): 
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
        return (isinstance(other, MockObject) and self._name == other._name) or (isinstance(other, str) and self._name == other)

class EmbeddingPrecision(str, Enum):
    FLOAT32 = "float32"
    FLOAT16 = "float16"
    BFLOAT16 = "bfloat16"
    INT8 = "int8"
    UINT8 = "uint8"
    FLOAT = "float"

def __getattr__(name):
    return MockObject(name)
