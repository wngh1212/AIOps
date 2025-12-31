import time

import boto3


def cleanup_resources():
    ec2 = boto3.client("ec2", region_name="ap-northeast-2")
    ec2_resource = boto3.resource("ec2", region_name="ap-northeast-2")

    print("Starting AWS Resource Cleanup for 'ap-northeast-2'...\n")

    vpcs = list(ec2_resource.vpcs.all())

    if not vpcs:
        print("No VPCs found to delete.")
        return

    print(f"Found {len(vpcs)} VPCs. Checking for cleanup candidates...")

    for vpc in vpcs:
        if vpc.is_default:
            print(f"Skipping Default VPC: {vpc.id}")
            continue

        print(f"\nTargeting VPC: {vpc.id}")

        try:
            for subnet in vpc.subnets.all():
                print(f"  - Deleting Subnet: {subnet.id}")
                subnet.delete()

            for igw in vpc.internet_gateways.all():
                print(f"  - Detaching & Deleting IGW: {igw.id}")
                igw.detach_from_vpc(VpcId=vpc.id)
                igw.delete()

            for sg in vpc.security_groups.all():
                if sg.group_name != "default":
                    print(f"  - Deleting SG: {sg.id}")
                    sg.delete()

            print(f"Deleting VPC: {vpc.id}")
            vpc.delete()
            print("  -> Deleted.")

        except Exception as e:
            print(f"❌ Error deleting dependencies for {vpc.id}: {e}")

    print("\nCleanup Complete!")


if __name__ == "__main__":
    cleanup_resources()
