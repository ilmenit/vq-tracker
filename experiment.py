class Encoder:
    def __init__(self, name):
        self.name = name
    
    def run(self, audio, sr, bin_export_path=None):
        raise NotImplementedError
