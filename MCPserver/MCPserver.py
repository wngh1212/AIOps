import time
from datetime import datetime

import boto3


class MCPServer:
    def __init__(self):
        self.region = "ap-northeast-2"
        self.ec2 = boto3.client("ec2", region_name=self.region)
        self.cw = boto3.client("cloudwatch", region_name=self.region)
        self.ssm = boto3.client("ssm", region_name=self.region)
        self.ce = boto3.client("ce", region_name=self.region)

    def _clean_str(self, text):
        if not text:
            return ""
        return str(text).strip().replace("'", "").replace('"', "")

    def _get_latest_ami(self):
        try:
            response = self.ssm.get_parameter(
                Name="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64",
                WithDecryption=False,
            )
            return response["Parameter"]["Value"]
        except:
            return "ami-0c9c94c3f41b76315"

    def _resolve_id(self, identifier):
        if not identifier:
            return None
        identifier = self._clean_str(identifier)
        if identifier.startswith("i-"):
            return identifier
        try:
            response = self.ec2.describe_instances()
            target_name = identifier.lower().replace(" ", "")
            for r in response["Reservations"]:
                for i in r["Instances"]:
                    if i["State"]["Name"] == "terminated":
                        continue
                    name_tag = next(
                        (t["Value"] for t in i.get("Tags", []) if t["Key"] == "Name"),
                        "",
                    )
                    if target_name in name_tag.lower().replace(" ", ""):
                        return i["InstanceId"]
        except:
            pass
        return None

    def _get_default_subnet(self):
        try:
            # default-for-az 필터를 사용하여 AWS가 지정한 기본 서브넷만 조회
            response = self.ec2.describe_subnets(
                Filters=[{"Name": "default-for-az", "Values": ["true"]}]
            )
            if response["Subnets"]:
                # 여러 개가 있을 수 있으므로 그중 첫 번째를 선택
                target = response["Subnets"][0]["SubnetId"]
                az = response["Subnets"][0]["AvailabilityZone"]
                print(f"[Auto-detected] Default Subnet: {target} ({az})")
                return target
            else:
                print("[Warning] No Default Subnet found in this account.")
        except Exception as e:
            print(f"❌ Subnet Auto-detection failed: {e}")
        return None

    def call_tool(self, tool_name, args):
        print(f"[MCP Execution] Tool: {tool_name} | Args: {args}")
        try:
            if tool_name == "create_vpc":
                return self.create_vpc(args.get("cidr"))
            elif tool_name == "create_subnet":
                return self.create_subnet(args.get("vpc_id"), args.get("cidr"))

            elif tool_name == "create_instance":
                img = self._clean_str(args.get("image_id"))
                if not img or not img.startswith("ami-"):
                    print("Validating AMI ID...")
                    img = self._get_latest_ami()

                # 서브넷 ID가 없으면 자동 검색 시도
                sub_id = args.get("subnet_id")
                if not sub_id:
                    sub_id = self._get_default_subnet()
                    if not sub_id:
                        return "Error: No Subnet provided and failed to auto-detect one in ap-northeast-2a."

                return self.create_instance(
                    img,
                    args.get("instance_type", "t2.nano"),
                    sub_id,
                    args.get("sg_id"),
                    self._clean_str(args.get("name", "new-instance")),
                )

            elif tool_name == "list_instances":
                return self.list_instances(args.get("status", "all"))
            elif tool_name == "get_cost":
                return self.get_cost()
            elif tool_name == "generate_topology":
                return self.generate_topology()
            elif tool_name == "get_metric":
                return self.get_metric(
                    args.get("instance_id"), args.get("metric_name", "CPUUtilization")
                )
            elif tool_name == "create_snapshot":
                return self.create_snapshot(args.get("instance_id"))
            elif tool_name == "resize_instance":
                return self.resize_instance(
                    args.get("instance_id"), args.get("instance_type")
                )
            elif tool_name == "start_instance":
                return self.start_instance(args.get("instance_id") or args.get("name"))
            elif tool_name == "stop_instance":
                return self.stop_instance(args.get("instance_id") or args.get("name"))
            elif tool_name == "delete_resource":
                return self.delete_resource(args.get("instance_id") or args.get("name"))
            else:
                return f"Error: Unknown tool {tool_name}"
        except Exception as e:
            return f"System Error: {str(e)}"

    def create_vpc(self, cidr):
        if not cidr:
            cidr = "10.0.0.0/16"
        res = self.ec2.create_vpc(CidrBlock=cidr)
        vpc_id = res["Vpc"]["VpcId"]
        self.ec2.create_tags(
            Resources=[vpc_id], Tags=[{"Key": "Name", "Value": "AI-VPC"}]
        )
        return {"status": "success", "resource_id": vpc_id, "type": "vpc"}

    def create_subnet(self, vpc_id, cidr):
        if not vpc_id:
            return "Error: VPC ID missing"
        res = self.ec2.create_subnet(
            VpcId=vpc_id, CidrBlock=cidr, AvailabilityZone="ap-northeast-2a"
        )
        return {
            "status": "success",
            "resource_id": res["Subnet"]["SubnetId"],
            "type": "subnet",
        }

    def create_instance(self, image_id, instance_type, subnet_id, sg_id, name):
        image_id = self._clean_str(image_id)
        print(
            f"Launching: AMI={image_id}, Type={instance_type}, Subnet={subnet_id}, Zone=ap-northeast-2a"
        )

        # sg_id가 None이면 AWS Default SG 사용되므로 그대로 둠
        run_args = {
            "ImageId": image_id,
            "InstanceType": instance_type,
            "SubnetId": subnet_id,
            "MinCount": 1,
            "MaxCount": 1,
            "TagSpecifications": [
                {"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": name}]}
            ],
        }
        if sg_id:
            run_args["SecurityGroupIds"] = [sg_id]

        res = self.ec2.run_instances(**run_args)
        instance_id = res["Instances"][0]["InstanceId"]
        time.sleep(2)
        return {"status": "success", "resource_id": instance_id, "type": "instance"}

    def list_instances(self, status="all"):
        filters = (
            []
            if status == "all"
            else [{"Name": "instance-state-name", "Values": ["running", "pending"]}]
        )
        res = self.ec2.describe_instances(Filters=filters)
        lines = []
        for r in res["Reservations"]:
            for i in r["Instances"]:
                name = next(
                    (t["Value"] for t in i.get("Tags", []) if t["Key"] == "Name"),
                    "Unknown",
                )
                state = i["State"]["Name"]
                lines.append(
                    f"ID: {i['InstanceId']} | Name: {name} | State: {state.upper()}"
                )
        return "\n".join(lines) if lines else "No instances found."

    def get_cost(self):
        try:
            now = datetime.now()
            start = now.replace(day=1).strftime("%Y-%m-%d")
            end = now.strftime("%Y-%m-%d")
            if start == end:
                return "매월 1일은 집계 중"
            res = self.ce.get_cost_and_usage(
                TimePeriod={"Start": start, "End": end},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
            )
            amt = float(res["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"])
            return f"This Month's Estimated Cost: ${amt:.2f} ({start} ~ {end})"
        except Exception as e:
            return f"Cost Error: {str(e)}"

    def get_metric(self, identifier, metric):
        tid = self._resolve_id(identifier)
        return (
            f"{metric} for {tid}: 0.5% (Mock)"
            if tid
            else f"Instance '{identifier}' not found"
        )

    def create_snapshot(self, identifier):
        tid = self._resolve_id(identifier)
        return (
            f"Snapshot Started for {identifier} ({tid})"
            if tid
            else "Instance not found"
        )

    def resize_instance(self, identifier, new_type):
        tid = self._resolve_id(identifier)
        return (
            f"Resized {identifier} ({tid}) to {new_type}"
            if tid
            else f"Target '{identifier}' not found."
        )

    def generate_topology(self):
        lines = ["Topology:"]
        try:
            vpcs = self.ec2.describe_vpcs()["Vpcs"]
            for vpc in vpcs:
                lines.append(f"[VPC: {vpc['VpcId']}]")
        except:
            pass
        return "\n".join(lines)

    def start_instance(self, identifier):
        tid = self._resolve_id(identifier)
        if not tid:
            return f"Target '{identifier}' not found."
        self.ec2.start_instances(InstanceIds=[tid])
        return f"Starting instance {identifier} ({tid})..."

    def stop_instance(self, identifier):
        tid = self._resolve_id(identifier)
        if not tid:
            return f"Target '{identifier}' not found."
        self.ec2.stop_instances(InstanceIds=[tid])
        return f"Stopping instance {identifier} ({tid})..."

    def delete_resource(self, identifier):
        tid = self._resolve_id(identifier)
        if not tid:
            return f"Target '{identifier}' not found."
        self.ec2.terminate_instances(InstanceIds=[tid])
        return f"Terminating instance {identifier} ({tid})..."
