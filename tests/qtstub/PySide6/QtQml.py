from .QtCore import QObject, Signal
class QQmlPropertyMap(QObject):
    valueChanged = Signal()
    def __init__(self, *a): super().__init__(); self.d = {}
    def insert(self, k, v): self.d[k] = v
    def value(self, k): return self.d[k]
    def set(self, k, v): self.d[k] = v; self.valueChanged.emit(k, v)
