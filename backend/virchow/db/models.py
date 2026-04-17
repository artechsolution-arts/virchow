import sys

class User:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

# Catch-all for missing models
def __getattr__(name):
    return type(name, (object,), {"__init__": lambda self, **kwargs: None})
