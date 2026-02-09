from diagrams import Diagram
from diagrams.aws.compute import EC2
from diagrams.aws.database import RDS
from diagrams.aws.storage import EBS
from diagrams.aws.storage import S3
from diagrams import Cluster

with Diagram("Aplicação Web", direction="TB"):
    with Cluster("Amazon Cloud"):
        amazon_ebs_v1 = EBS("Amazon EBS")

        ec2_cloud_v1 = EC2("Amazon EC2")
        rds_amazon_v1 = RDS("Amazon RDS")

        ec2_cloud_v2 = EC2("Amazon EC2")
        rds_amazon_v2 = RDS("Amazon RDS")

        s3_amazon = S3("Amazon S3")
        amazon_ebs_v2 = EBS("Amazon EBS")


        with Cluster("Availability Zone 1"):
            workers = [EC2("Amazon EC2"), EC2("Amazon EC2"), EBS("Amazon EBS"), RDS("Amazon RDS")]


        with Cluster("Availability Zone 2"):
            workers_v2= [EC2("Amazon EC2"), EC2("Amazon EC2"), EBS("Amazon EBS"), RDS("Amazon RDS")]
        
        amazon_ebs_v1 - ec2_cloud_v1 >> ec2_cloud_v2 >> ec2_cloud_v1
        
        ec2_cloud_v1 - rds_amazon_v1
        ec2_cloud_v2 - amazon_ebs_v2
        ec2_cloud_v2 - s3_amazon
        ec2_cloud_v2 - rds_amazon_v2

        ec2_cloud_v1 >> [workers[0], workers_v2[0]]

        workers[0] >> workers[1]
        workers[0] - workers[2]
        workers[0] >> workers[3]

        workers_v2[0] >> workers_v2[1]
        workers_v2[0] - workers_v2[2]
        workers_v2[0] >> workers_v2[3]

        ec2_cloud_v2 >> [workers[0], workers_v2[0]]
        workers[0] >> [workers[1], workers[2]]
        workers[0] - workers[3]

        workers_v2[0] >> [workers_v2[1], workers_v2[2]]
        workers_v2[0] - workers_v2[3]