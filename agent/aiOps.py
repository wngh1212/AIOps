import json
import re


class ChatOpsClient:
    def __init__(self, mcp_server, llm):
        self.server = mcp_server
        self.llm = llm

    def _extract_python_code(self, text):
        pattern = r"```python(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            return "\n".join(matches).strip()

        pattern_generic = r"```(.*?)```"
        matches_generic = re.findall(pattern_generic, text, re.DOTALL)
        if matches_generic:
            return "\n".join(matches_generic).strip()

        #  파이썬 코드처럼 보이는 라인만 필터링
        lines = text.split("\n")
        code_lines = []
        for line in lines:
            s = line.strip()
            # 번호 매기기(1. 2.) 등으로 시작하면 스킵
            if re.match(r"^\d+\.", s):
                continue
            # 일반적인 텍스트 문장은 스킵 (단, =, (, #, import 등이 있으면 코드로 간주)
            if re.match(r"^(import|from|print|ec2|s3|def|class|#)", s) or (
                "=" in s and "(" in s
            ):
                code_lines.append(line)

        return "\n".join(code_lines) if code_lines else text.strip()

    def _auto_fix_code(self, code):
        """
        [Auto-Fix] 구문 오류(Syntax Error) 및 환각 교정
        """
        fixed = code

        # 모든 import 문 제거 (import ec2, import boto3 등 방지)
        fixed = re.sub(r"^\s*import\s+.*$", "", fixed, flags=re.MULTILINE)
        fixed = re.sub(r"^\s*from\s+.*$", "", fixed, flags=re.MULTILINE)

        #  클라이언트 객체 재할당 방지
        # ec2 = boto3.client(...) 패턴을 주석 처리하거나 무력화
        if "boto3.client" in fixed:
            fixed = re.sub(
                r"(\w+)\s*=\s*boto3\.client.*", r"# \1 client is pre-loaded", fixed
            )

        # security-group 서비스 환각 수정
        if "client('security-group')" in fixed or 'client("security-group")' in fixed:
            fixed = fixed.replace("client('security-group')", "ec2")
            fixed = fixed.replace('client("security-group")', "ec2")

        # 파라미터 교정 (CidrIp -> CidrBlock)
        fixed = fixed.replace("CidrIp=", "CidrBlock=")
        fixed = fixed.replace("Cidr=", "CidrBlock=")

        #  Security Group Description 강제 주입
        if "create_security_group" in fixed and "Description" not in fixed:
            fixed = re.sub(
                r"(GroupName\s*=\s*['\"][^'\"]+['\"])",
                r"\1, Description='Auto-generated SG'",
                fixed,
            )

        # Bucket='name' 뒤에 설정을 안전하게 삽입
        if "create_bucket" in fixed and "CreateBucketConfiguration" not in fixed:
            fixed = re.sub(
                r"(Bucket\s*=\s*['\"][^'\"]+['\"])",
                r"\1, CreateBucketConfiguration={'LocationConstraint': 'ap-northeast-2'}",
                fixed,
            )

        # S3 불필요 파라미터 제거
        if "create_bucket" in fixed and "VpcId=" in fixed:
            fixed = re.sub(r",?\s*VpcId\s*=\s*[^,)]+", "", fixed)

        return fixed

    def chat(self, user_input):
        input_lower = user_input.lower()

        if "sop" in input_lower or "guideline" in input_lower:
            print("[System] SOP Search")
            query = user_input.replace("SOP", "").replace("find", "").strip()
            return self.server.call_tool("search_sop", {"query": query})

        # 프롬프트 개선
        # 설명 텍스트를 제거하고 순수 코드 예시만 제공
        prompt = f"""
        [ROLE]
        Python Automation Script Generator.

        [ENVIRONMENT]
        - Variables `ec2`, `s3` are PRE-LOADED. Use them directly.
        - NO imports allowed. NO re-initialization allowed.

        [CORRECT CODE EXAMPLES - COPY THESE PATTERNS]
        # Create VPC
        vpc = ec2.create_vpc(CidrBlock='10.0.0.0/16')
        print(vpc['Vpc']['VpcId'])

        # Create Subnet
        sub = ec2.create_subnet(VpcId='vpc-xxx', CidrBlock='10.0.1.0/24')
        print(sub['Subnet']['SubnetId'])

        # Create Security Group
        sg = ec2.create_security_group(GroupName='MySG', Description='My SG', VpcId='vpc-xxx')
        print(sg['GroupId'])

        # Create S3 Bucket
        s3.create_bucket(Bucket='my-bucket')
        print("Success")

        [REQUEST]
        "{user_input}"

        [OUTPUT REQUIREMENT]
        - Return ONLY the executable Python code block.
        - Do not include "Here is the code" or markdown text.
        """

        raw = self.llm.invoke(prompt)
        clean = self._extract_python_code(raw)
        final = self._auto_fix_code(clean)

        print(f"\n[DEBUG CODE]\n{final}\n{'-' * 20}")

        result = self.server.call_tool("execute_python_code", {"code_str": final})
        return f"[Result]\n{result}"
