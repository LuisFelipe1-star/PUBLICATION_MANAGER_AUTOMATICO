import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("validate_manifest",ROOT/"scripts"/"validate_manifest.py")
VALIDATOR=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(VALIDATOR)


class ManifestValidationTests(unittest.TestCase):
    def item(self,item_id="parte_17",title="Título",description="Descrição"):
        number=int(item_id.rsplit("_",1)[1]);return {"id":item_id,"video_path":item_id+".mp4","caption":f"Título:\n{title}\n\nPARTE {number}\nSiga @conta\n\nDescrição:\n{description}\n\nHashtags:\n#Teste"}
    def test_valid_manifest(self):
        errors,warnings,review=VALIDATOR.validate({"videos":[self.item()]},{"published":["parte_17"],"completed_slots":["2026-08-31:1245"]})
        self.assertEqual(errors,[]);self.assertEqual(warnings,[]);self.assertEqual(len(review),1)
    def test_duplicate_ids_and_unknown_state_fail(self):
        item=self.item();errors,_,_=VALIDATOR.validate({"videos":[item,item]},{"published":["parte_99"]})
        self.assertTrue(any("duplicados" in error for error in errors));self.assertTrue(any("fora do manifesto" in error for error in errors))
    def test_suspicious_content_is_reported(self):
        _,warnings,_=VALIDATOR.validate({"videos":[self.item(title="Luna Nova")]},{"published":[]})
        self.assertTrue(any("aluna nova" in warning for warning in warnings))


if __name__=="__main__":unittest.main()
