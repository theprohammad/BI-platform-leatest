class SharedMemory:

    def __init__(self):

        self.memory = {}

    def set(self, key, value):

        self.memory[key] = value

    def get(self, key, default=None):

        return self.memory.get(key, default)

    def all(self):

        return self.memory

    def clear(self):

        self.memory = {}