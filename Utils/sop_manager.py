import os

import chromadb


class SOPManager:
    def __init__(self, file_path="sop.txt"):
        self.file_path = file_path
        self.chroma_client = chromadb.Client()
        self.collection = self.chroma_client.get_or_create_collection(name="aws_asop")
        self.load_sop()

    def load_sop(self):
        if os.path.exists(self.file_path):
            with open(self.file_path, "r", encoding="utf-8") as f:
                content = f.read()
                # CASE 단위로 분리하여 인덱싱
                sections = content.split("[CASE:")
                for i, section in enumerate(sections):
                    if section.strip():
                        self.collection.upsert(
                            documents=[section.strip()], ids=[f"sop_rule_{i}"]
                        )
            print(f"SOP Manager: {self.file_path} 로드 완료")
        else:
            print(f"SOP Manager: {self.file_path}를 찾을 수 없습니다.")

    def search_guideline(self, query):
        results = self.collection.query(query_texts=[query], n_results=1)
        if results["documents"]:
            return results["documents"][0][0]
        return "No matching SOP found."
