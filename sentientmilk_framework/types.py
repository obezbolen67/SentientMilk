class ModulesContainer:
    def __init__(self, **modules):
        for name, module in modules.items():
            setattr(self, name, module)