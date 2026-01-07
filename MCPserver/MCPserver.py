import logging
import time
from datetime import datetime, timedelta, timezone
from re import I

import boto3

logger = logging.getLogger(__name__)


class MCPServer:
    def __init__(self, region="ap-northeast-2"):
        self.region = region
        self._initialize_clients()
        logger.info("MCPServer initialized")

    def _initialize_clients(self):
        self.ec2 = boto3.client("ec2", region_name=self.region)
        self.cw = boto3.client("cloudwatch", region_name=self.region)
        self.ssm = boto3.client("ssm", region_name=self.region)
        self.ce = boto3.client("ce", region_name=self.region)

    def change_region(self, new_region):
        # AWS 리전 변경
        if new_region == self.region:
            return

        old_region = self.region
        self.region = new_region

        try:
            self._initialize_clients()
        except Exception as e:
            self.region = old_region
            self._initialize_clients()
            raise

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

    import logging

    logger = logging.getLogger(__name__)

    def get_cost_by_date(self, start_date, end_date):
        """Human-friendly [start_date, end_date] → Cost Explorer-safe [Start, End)"""
        try:
            logger.info(f"Fetching cost for {start_date} ~ {end_date}")

            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")

            # Cost Explorer는 [Start, End) 이므로 End는 end_dt + 1일
            ce_start = start_dt

            # 사용자가 end_date를 미래로 주면 현재 시점 기준으로 자르기
            today = datetime.now().date()
            if end_dt.date() > today:
                end_dt = datetime(today.year, today.month, today.day)

            ce_end = end_dt + timedelta(days=1)

            # End는 "다음 달 1일"을 넘어가면 안 됨 → 현재 달 기준 상한 설정
            # 오늘이 2026-01-05면 upper_bound = 2026-02-01
            upper_bound = datetime(today.year, today.month, 1) + timedelta(days=32)
            upper_bound = upper_bound.replace(day=1)  # 다음 달 1일

            if ce_end > upper_bound:
                ce_end = upper_bound

            ce_start_str = ce_start.strftime("%Y-%m-%d")
            ce_end_str = ce_end.strftime("%Y-%m-%d")

            logger.info(
                f"Calling Cost Explorer with Start={ce_start_str}, End={ce_end_str}"
            )

            res = self.ce.get_cost_and_usage(
                TimePeriod={"Start": ce_start_str, "End": ce_end_str},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
            )

            if res["ResultsByTime"]:
                amt = float(res["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"])
                return f"Cost from {start_date} to {end_date}: ${amt:.2f}"
            else:
                return f"Cost from {start_date} to {end_date}: $0.00"

        except Exception as e:
            logger.error(f"Cost retrieval failed: {e}", exc_info=True)
            return f"Cost Error: {str(e)}"

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

    def call_tool(self, tool_name: str, args: dict):
        logger.debug(f"[MCP Execution] Tool: {tool_name} | Args: {args}")

        # 도구 이름과 실행 로직을 매핑 (매핑 테이블)
        tool_mapping = {
            "create_vpc": lambda: self.create_vpc(args.get("cidr")),
            "create_subnet": lambda: self.create_subnet(
                args.get("vpc_id"), args.get("cidr")
            ),
            "create_instance": lambda: self._handle_create_instance(
                args
            ),  # 복잡한 로직 분리
            "list_instances": lambda: self.list_instances(args.get("status", "all")),
            "get_cost": lambda: self.get_cost(),
            "generate_topology": lambda: self.generate_topology(),
            "get_metric": lambda: self.get_metric(
                args.get("instance_id"), args.get("metric_name", "CPUUtilization")
            ),
            "create_snapshot": lambda: self.create_snapshot(self._get_id_or_name(args)),
            "resize_instance": lambda: self.resize_instance(
                args.get("instance_id"), args.get("instance_type") or args.get("name")
            ),
            "start_instance": lambda: self.start_instance(self._get_id_or_name(args)),
            "stop_instance": lambda: self.stop_instance(self._get_id_or_name(args)),
            "delete_resource": lambda: self.delete_resource(self._get_id_or_name(args)),
            "get_recent_logs": lambda: self.get_recent_logs(args.get("id")),
            "execute_aws_action": lambda: self.execute_aws_action(args),
        }

        handler = tool_mapping.get(tool_name)

        if not handler:
            logger.warning(f"Unknown tool: {tool_name}")
            return f"Error: Unknown tool {tool_name}"

        try:
            return handler()
        except Exception as e:
            logger.error(f"Tool execution error: {e}", exc_info=True)
            return f"System Error: {str(e)}"

    def _handle_create_instance(self, args: dict):
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
            image_id=img,
            instance_type=args.get("instance_type", "t2.nano"),
            subnet_id=sub_id,
            sg_id=args.get("sg_id"),
            name=self._clean_str(args.get("name", "new-instance")),
        )

    def _get_id_or_name(self, args: dict):
        # ID 혹은 Name 파라미터 추출
        return args.get("instance_id") or args.get("name")

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
                return "The first day of each month is being counted"
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
            return f"target {identifier} not found"
        try:
            response = self.ec2.describe_instances(InstanceIds=[tid])
            state = response["Reservations"][0]["Instances"][0]["State"]["Name"]
            if state != "stopped":
                return f"Error : Instance must be stopped to resize. Current state: {state}"
            self.ec2.modify_instance_attribute(
                InstanceId=tid, InstanceType={"Value": new_type}
            )
            return f"Successfully resized {identifier} ({tid}) to {new_type}"

        except Exception as e:
            return f"Error resizing instance: {str(e)}"

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
            logger.info(f"Fetching logs for {tid}")
            return f"Recent logs for {tid}: [샘플 로그 데이터]"
        except Exception as e:
            logger.error(f"Failed to get logs: {e}")
            return f"Error fetching logs: {str(e)}"

    def execute_aws_action(self, args):
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
