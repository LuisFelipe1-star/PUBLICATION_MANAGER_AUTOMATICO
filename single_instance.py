import os
_handle=None
def acquire():
 global _handle
 if os.name!='nt':return True
 import ctypes
 _handle=ctypes.windll.kernel32.CreateMutexW(None,False,'Local\\PublicationManagerAutomatico')
 return ctypes.windll.kernel32.GetLastError()!=183
