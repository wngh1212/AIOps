import logging
import os

import chromadb

logger = logging.getLogger(__name__)


class SOPManager:
    def __init__(self, file_path="SOP/sop.yaml", persist_dir="./chroma_data"):
        self.file_path = file_path

        self.chroma_client = chromadb.PersistentClient(path=persist_dir)

        self.collection = self.chroma_client.get_or_create_collection(
            name="aws_sop",
            metadata={"hnsw:space": "cosine"},
        )

        self.load_sop()

    def load_sop(self):
        import yaml

        if not os.path.exists(self.file_path):
            logger.warning(f"SOP file not found: {self.file_path}")
            return

        with open(self.file_path, "r", encoding="utf-8") as f:
            sop_data = yaml.safe_load(f)
            # 룰별메타데이타 포함 저장
            rules = sop_data.get("rules", {})

        for rule_id, rule_content in rules.items():
            self.collection.upsert(
                documents=[rule_content["description"]],
                metadatas=[
                    {
                        "rule_id": rule_id,
                        "severity": rule_content.get("severity"),
                        "action_type": rule_content.get("action_type"),
                    }
                ],
                ids=[rule_id],
            )

        logger.info(f"Loaded {len(sop_data)} SOP rules")

    def search_guideline(self, query, n_results=3):
        # 복수 결과 반환 -> 신뢰도 향상
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        # 벡터 유사도 점수 보여주기
        output = []
        for doc, meta, distance in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            output.append(
                {
                    "rule_id": meta.get("rule_id"),
                    "content": doc,
                    "confidence": max(0.0, 1.0 - distance),  # 거리 >> 신뢰도
                }
            )

        return output
