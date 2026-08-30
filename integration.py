from __future__ import annotations
import json
from pathlib import Path

class FolderResolver:
    """Finds a nearby Auto Video Cutter without scanning the whole drive."""
    MARKERS=("config.json","main.py","backend","gui")
    def __init__(self, publication_root: Path): self.publication_root=Path(publication_root).resolve()
    @staticmethod
    def _config(root: Path):
        path=root/"config.json"
        try:
            data=json.loads(path.read_text(encoding="utf-8-sig"))
            folders=data.get("folders",{})
            if not isinstance(folders,dict) or "output" not in folders:return None
            if not ((root/"main.py").exists() and ((root/"backend").is_dir() or (root/"src").is_dir())):return None
            return data
        except (OSError,ValueError,TypeError):return None
    @staticmethod
    def resolve_path(root: Path,value: str):
        p=Path(value).expanduser()
        return p.resolve() if p.is_absolute() else (root/p).resolve()
    def inspect(self,root):
        root=Path(root).expanduser().resolve();data=self._config(root)
        if not data:raise ValueError("A pasta escolhida não parece ser um projeto Auto Video Cutter válido.")
        f=data["folders"]
        return {"project_dir":str(root),"input_dir":str(self.resolve_path(root,f.get("input","input"))),"output_dir":str(self.resolve_path(root,f["output"])),"config_path":str(root/"config.json")}
    def candidates(self,previous=""):
        roots=[]
        if previous:roots.append(Path(previous).expanduser())
        here=self.publication_root
        for base in (here,here.parent,here.parent.parent,Path.cwd()):
            roots.append(base)
            try:roots.extend(p for p in base.iterdir() if p.is_dir())
            except OSError:pass
        seen=set()
        for root in roots:
            try:key=str(root.resolve()).casefold()
            except OSError:continue
            if key in seen:continue
            seen.add(key);yield root
    def detect(self,previous=""):
        matches=[]
        for root in self.candidates(previous):
            if self._config(root):matches.append(self.inspect(root))
        if not matches:raise FileNotFoundError("Auto Video Cutter não foi encontrado nas pastas próximas. Escolha a pasta do projeto manualmente.")
        return matches[0]

class AutoVideoCutterIntegration:
    def __init__(self,resolver:FolderResolver):self.resolver=resolver
    def link(self,project_dir):return self.resolver.inspect(project_dir)
    def refresh(self,project_dir):return self.resolver.inspect(project_dir)
