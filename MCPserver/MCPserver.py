import json

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from Utils.aws_tools import AWSTools
from Utils.sop_manager import SOPManager


class MCPServer:
    def __init__(self):
        # 도구 및 데이터 초기화
        self.aws = AWSTools()
        self.sop_manager = SOPManager()

        # 검색용 임베딩 모델 (로컬 로드)
        # 처음 실행 시 모델 다운로드로 시간이 조금 걸릴 수 있음
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

        # === [핵심] 도구 레지스트리 ===
        # 정적 도구: 자주 쓰이고 안정성이 중요한 조회/모니터링용
        # 동적 도구: execute_python_code (그 외 모든 작업용)
        self.tools = {
            "list_instances": self.aws.get_inventory,
            "get_recent_logs": self.aws.get_recent_logs,
            "execute_python_code": self.aws.execute_python_code,  # 만능 도구
            "search_sop": self.sop_manager.search_guideline,
        }

        # 도구 설명 (Vector Search용)
        self.tool_descriptions = [
            "list_instances: Show all EC2 instances status, CPU, and state.",
            "get_recent_logs: Fetch recent system logs from an instance for debugging.",
            "execute_python_code: Write and run Python Boto3 code to create, delete, or manage AWS resources (VPC, RDS, S3, EC2, etc).",
            "search_sop: Find standard operating procedures and guidelines.",
        ]

        # 설명 임베딩 캐싱
        self.tool_embeddings = self.model.encode(self.tool_descriptions)

    def find_best_tool(self, user_query):
        """
        사용자 질문과 가장 유사한 도구를 찾습니다.
        복잡한 생성/제어 명령은 'execute_python_code'로 유도됩니다.
        """
        # 1. 키워드 기반 빠른 매칭 (우선순위)
        query_lower = user_query.lower()

        # 생성, 삭제, 설정 변경 등은 무조건 코드로 실행하도록 유도
        code_keywords = [
            "create",
            "make",
            "delete",
            "terminate",
            "change",
            "update",
            "run",
            "launch",
            "rds",
            "vpc",
            "s3",
        ]
        if any(k in query_lower for k in code_keywords):
            # 단, list/show 키워드가 같이 있으면 조회 툴을 우선할 수도 있음
            if "list" not in query_lower and "show" not in query_lower:
                return "execute_python_code"

        # 2. Vector Search (임베딩 유사도 검색)
        query_vec = self.model.encode([user_query])
        similarities = cosine_similarity(query_vec, self.tool_embeddings)[0]
        best_idx = similarities.argmax()

        # 유사도가 너무 낮으면 기본적으로 코드 실행을 제안
        if similarities[best_idx] < 0.3:
            return "execute_python_code"

        return self.tools_keys()[best_idx]

    def tools_keys(self):
        return list(self.tools.keys())

    def call_tool(self, tool_name, params=None):
        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' not found."

        try:
            func = self.tools[tool_name]

            # 파라미터가 없으면 함수 그냥 실행
            if not params:
                return func()

            # execute_python_code는 단일 문자열 인자 처리가 필요할 수 있음
            if tool_name == "execute_python_code" and "code_str" in params:
                return func(params["code_str"])

            # 그 외 딕셔너리 언패킹 실행
            return func(**params)

        except Exception as e:
            return f"Tool Execution Error: {e}"
