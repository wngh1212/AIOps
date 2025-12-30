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

        return text.strip()

    def _auto_fix_code(self, code):
        fixed = code

        fixed = re.sub(r"^import boto3.*$", "", fixed, flags=re.MULTILINE)

        # ec2 = boto3.client(...) -> ec2 = ec2
        fixed = re.sub(r"(\w+)\s*=\s*boto3\.client.*", r"\1 = \1", fixed)

        # security-group 서비스 환각 수정
        # 모델이 boto3.client('security-group')을 시도하면 ec2로 변경
        if "client('security-group')" in fixed or 'client("security-group")' in fixed:
            fixed = fixed.replace("client('security-group')", "ec2")
            fixed = fixed.replace('client("security-group")', "ec2")

        #  VPC 파라미터 수정 (CidrIp -> CidrBlock)
        fixed = fixed.replace("CidrIp=", "CidrBlock=")
        fixed = fixed.replace("Cidr=", "CidrBlock=")

        # Security Group - Description 강제 주입
        # create_security_group 호출 시 Description이 없으면 추가
        if "create_security_group" in fixed and "Description" not in fixed:
            fixed = re.sub(
                r"(GroupName\s*=\s*['\"][^'\"]+['\"])",
                r"\1, Description='Auto-generated SG'",
                fixed,
            )

        # S3 Config 주입
        # 괄호 짝을 깨지 않도록 create_bucket 함수 내부에만 주입
        if "create_bucket" in fixed and "CreateBucketConfiguration" not in fixed:
            fixed = re.sub(
                r"(Bucket\s*=\s*['\"][^'\"]+['\"])",
                r"\1, CreateBucketConfiguration={'LocationConstraint': 'ap-northeast-2'}",
                fixed,
            )

        if "create_bucket" in fixed and "VpcId=" in fixed:
            fixed = re.sub(r",?\s*VpcId\s*=\s*[^,)]+", "", fixed)

        return fixed

    def chat(self, user_input):
        input_lower = user_input.lower()

        if "sop" in input_lower or "guideline" in input_lower:
            print("[System] SOP Search")
            query = user_input.replace("SOP", "").replace("find", "").strip()
            return self.server.call_tool("search_sop", {"query": query})

        prompt = f"""
        [ROLE]
        You are an AWS Python Automation Expert.

        [CONTEXT]
        - Variables `ec2`, `s3` are ALREADY initialized. Use them directly.
        - **Security Groups** are managed via `ec2` client (NOT 'security-group' client).
        - **Subnets** require `VpcId` and `CidrBlock`.
        - **S3 Buckets** do NOT assume `VpcId`.

        [CODE TEMPLATES (Follow these exactly)]
        1. Create VPC:
           vpc = ec2.create_vpc(CidrBlock='10.0.0.0/16')
           print(vpc['Vpc']['VpcId'])

        2. Create Subnet:
           sub = ec2.create_subnet(VpcId='vpc-xxx', CidrBlock='10.0.1.0/24')
           print(sub['Subnet']['SubnetId'])

        3. Create Security Group:
           sg = ec2.create_security_group(GroupName='MySG', Description='My SG', VpcId='vpc-xxx')
           print(sg['GroupId'])

        4. Create S3:
           s3.create_bucket(Bucket='my-bucket')
           print("Success")

        [REQUEST]
        Generate Python code for: "{user_input}"

        [CONSTRAINT]
        - Output ONLY the Python code block.
        - Do not import boto3.
        - Do not re-initialize clients.
        """

        raw = self.llm.invoke(prompt)
        clean = self._extract_python_code(raw)
        final = self._auto_fix_code(clean)

        print(f"\n[DEBUG CODE]\n{final}\n{'-' * 20}")

        result = self.server.call_tool("execute_python_code", {"code_str": final})
        return f"[Result]\n{result}"
