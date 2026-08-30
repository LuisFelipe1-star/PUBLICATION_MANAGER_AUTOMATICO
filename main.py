from tkinter import messagebox
from single_instance import acquire
if __name__=='__main__':
 if not acquire():messagebox.showwarning('Publication Manager','O programa já está em execução.')
 else:
  from app import App
  App().run()
