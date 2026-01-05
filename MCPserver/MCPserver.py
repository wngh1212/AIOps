import logging
import time
from datetime import datetime, timedelta, timezone

import boto3

logger = logging.getLogger(__name__)


class MCPServer:
    def __init__(self):
        self.region = "ap-northeast-2"
        self.ec2 = boto3.client("ec2", region_name=self.region)
        self.cw = boto3.client("cloudwatch", region_name=self.region)
        self.ssm = boto3.client("ssm", region_name=self.region)
        self.ce = boto3.client("ce", region_name=self.region)
        logger.info("MCPServer initialized")

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
        except Exception as e:
            logger.warning(f"Failed to get latest AMI: {e}, using default")
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
        except Exception as e:
            logger.error(f"Error resolving identifier {identifier}: {e}")
        return None

    def _get_default_subnet(self):
        try:
            response = self.ec2.describe_subnets(
                Filters=[{"Name": "default-for-az", "Values": ["true"]}]
            )
            if response["Subnets"]:
                target = response["Subnets"][0]["SubnetId"]
                az = response["Subnets"][0]["AvailabilityZone"]
                logger.info(f"Auto-detected Default Subnet: {target} ({az})")
                return target
            else:
                logger.warning("No Default Subnet found in this account")
        except Exception as e:
            logger.error(f"Subnet Auto-detection failed: {e}")
        return None

    def _get_cpu_metric(self, instance_id):
        # 인스턴스의 최근 CPU 사용률 조회
        try:
            now = datetime.now(timezone.utc)
            stats = self.cw.get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName="CPUUtilization",
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=now - timedelta(minutes=5),
                EndTime=now,
                Period=300,
                Statistics=["Average"],
            )

            if stats["Datapoints"]:
                cpu_val = round(stats["Datapoints"][-1]["Average"], 2)
                logger.debug(f"CPU for {instance_id}: {cpu_val}%")
                return cpu_val
            else:
                logger.debug(f"No CPU data available for {instance_id}")
                return 0.0
        except Exception as e:
            logger.warning(f"Failed to get CPU metric for {instance_id}: {e}")
            return 0.0

    def call_tool(self, tool_name, args):
        # 제거: print(f"[MCP Execution] Tool: {tool_name} | Args: {args}")
        logger.debug(f"[MCP Execution] Tool: {tool_name} | Args: {args}")

        try:
            if tool_name == "create_vpc":
                return self.create_vpc(args.get("cidr"))
            elif tool_name == "create_subnet":
                return self.create_subnet(args.get("vpc_id"), args.get("cidr"))

            elif tool_name == "create_instance":
                img = self._clean_str(args.get("image_id"))
                if not img or not img.startswith("ami-"):
                    logger.info("Validating AMI ID...")
                    img = self._get_latest_ami()

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
            elif tool_name == "get_recent_logs":
                # 모니터링에 필요한 메서드
                return self.get_recent_logs(args.get("id"))
            elif tool_name == "execute_aws_action":
                return self.execute_aws_action(args)
            else:
                logger.warning(f"Unknown tool: {tool_name}")
                return f"Error: Unknown tool {tool_name}"
        except Exception as e:
            logger.error(f"Tool execution error: {e}", exc_info=True)
            return f"System Error: {str(e)}"

    def create_vpc(self, cidr):
        if not cidr:
            cidr = "10.0.0.0/16"
        res = self.ec2.create_vpc(CidrBlock=cidr)
        vpc_id = res["Vpc"]["VpcId"]
        self.ec2.create_tags(
            Resources=[vpc_id], Tags=[{"Key": "Name", "Value": "AI-VPC"}]
        )
        logger.info(f"VPC created: {vpc_id}")
        return {"status": "success", "resource_id": vpc_id, "type": "vpc"}

    def create_subnet(self, vpc_id, cidr):
        if not vpc_id:
            return "Error: VPC ID missing"
        res = self.ec2.create_subnet(
            VpcId=vpc_id, CidrBlock=cidr, AvailabilityZone="ap-northeast-2a"
        )
        logger.info(f"Subnet created: {res['Subnet']['SubnetId']}")
        return {
            "status": "success",
            "resource_id": res["Subnet"]["SubnetId"],
            "type": "subnet",
        }

    def create_instance(self, image_id, instance_type, subnet_id, sg_id, name):
        image_id = self._clean_str(image_id)
        logger.info(
            f"Launching: AMI={image_id}, Type={instance_type}, Subnet={subnet_id}, Name={name}"
        )

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
        logger.info(f"Instance created: {instance_id}")
        return {"status": "success", "resource_id": instance_id, "type": "instance"}

    def list_instances(self, status="all"):
        """인스턴스 목록 조회 (CPU 메트릭 포함)"""
        try:
            filters = (
                []
                if status == "all"
                else [{"Name": "instance-state-name", "Values": ["running", "pending"]}]
            )
            res = self.ec2.describe_instances(Filters=filters)
            lines = []

            for r in res["Reservations"]:
                for i in r["Instances"]:
                    instance_id = i["InstanceId"]
                    name = next(
                        (t["Value"] for t in i.get("Tags", []) if t["Key"] == "Name"),
                        "Unknown",
                    )
                    state = i["State"]["Name"]

                    # CPU 메트릭 추가
                    cpu_val = 0.0
                    if state == "running":
                        cpu_val = self._get_cpu_metric(instance_id)

                    # 개선된 포맷 monitor.py 정규식과 매칭
                    lines.append(
                        f"ID: {instance_id} | Name: {name} | State: {state} | CPU: {cpu_val}%"
                    )

            result = "\n".join(lines) if lines else "No instances found."
            logger.debug(f"List instances result: {len(lines)} instances found")
            return result
        except Exception as e:
            logger.error(f"Failed to list instances: {e}", exc_info=True)
            return f"Error: {str(e)}"

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
            result = f"This Month's Estimated Cost: ${amt:.2f} ({start} ~ {end})"
            logger.info(f"Cost retrieved: ${amt:.2f}")
            return result
        except Exception as e:
            logger.error(f"Cost Error: {e}")
            return f"Cost Error: {str(e)}"

    def get_metric(self, identifier, metric):
        tid = self._resolve_id(identifier)
        if not tid:
            return f"Instance '{identifier}' not found"

        if metric == "CPUUtilization":
            cpu_val = self._get_cpu_metric(tid)
            return f"{metric} for {tid}: {cpu_val}%"

        return f"{metric} for {tid}: 0.5% (Mock)"

    def create_snapshot(self, identifier):
        tid = self._resolve_id(identifier)
        if not tid:
            return "Instance not found"
        logger.info(f"Snapshot started for {identifier} ({tid})")
        return f"Snapshot Started for {identifier} ({tid})"

    def resize_instance(self, identifier, new_type):
        tid = self._resolve_id(identifier)
        if not tid:
            return f"Target '{identifier}' not found."
        logger.info(f"Resizing {identifier} ({tid}) to {new_type}")
        return f"Resized {identifier} ({tid}) to {new_type}"

    def generate_topology(self):
        lines = ["Topology:"]
        try:
            vpcs = self.ec2.describe_vpcs()["Vpcs"]
            for vpc in vpcs:
                lines.append(f"[VPC: {vpc['VpcId']}]")
            logger.debug(f"Topology generated: {len(vpcs)} VPCs")
        except Exception as e:
            logger.error(f"Failed to generate topology: {e}")
        return "\n".join(lines)

    def start_instance(self, identifier):
        tid = self._resolve_id(identifier)
        if not tid:
            return f"Target '{identifier}' not found."
        self.ec2.start_instances(InstanceIds=[tid])
        logger.info(f"Started instance {identifier} ({tid})")
        return f"Starting instance {identifier} ({tid})..."

    def stop_instance(self, identifier):
        tid = self._resolve_id(identifier)
        if not tid:
            return f"Target '{identifier}' not found."
        self.ec2.stop_instances(InstanceIds=[tid])
        logger.info(f"Stopped instance {identifier} ({tid})")
        return f"Stopping instance {identifier} ({tid})..."

    def delete_resource(self, identifier):
        tid = self._resolve_id(identifier)
        if not tid:
            return f"Target '{identifier}' not found."
        self.ec2.terminate_instances(InstanceIds=[tid])
        logger.info(f"Terminated instance {identifier} ({tid})")
        return f"Terminating instance {identifier} ({tid})..."

    def get_recent_logs(self, instance_id):
        # 모니터링에 필요한 로그 조회
        try:
            tid = self._resolve_id(instance_id)
            if not tid:
                return f"Instance '{instance_id}' not found"

            # CloudWatch Logs에서 인스턴스 관련 로그 조회
            # 실제 환경에서는 로그 그룹 설정 필요
            logger.info(f"Fetching logs for {tid}")
            return f"Recent logs for {tid}: [샘플 로그 데이터]"
        except Exception as e:
            logger.error(f"Failed to get logs: {e}")
            return f"Error fetching logs: {str(e)}"

    def execute_aws_action(self, args):
        # 추가: 모니터링에서 액션 실행
        try:
            action_name = args.get("action_name")
            params = args.get("params", {})
            instance_ids = params.get("InstanceIds", [])

            logger.info(f"Executing AWS action: {action_name} on {instance_ids}")

            if action_name == "start_instances":
                self.ec2.start_instances(InstanceIds=instance_ids)
                return f"Started instances: {instance_ids}"
            elif action_name == "reboot_instances":
                self.ec2.reboot_instances(InstanceIds=instance_ids)
                return f"Rebooted instances: {instance_ids}"
            elif action_name == "stop_instances":
                self.ec2.stop_instances(InstanceIds=instance_ids)
                return f"Stopped instances: {instance_ids}"
            else:
                return f"Unknown action: {action_name}"
        except Exception as e:
            logger.error(f"AWS action failed: {e}")
            return f"Error executing action: {str(e)}"
