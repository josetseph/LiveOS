"""S3-compatible cloud storage utilities for file upload, retrieval, and deletion."""
# pylint: disable=wrong-import-order
from aioboto3 import session as aioboto3_session
from app.core.config import settings
from app.core.log import get_logger
from botocore.client import Config

# Initialize logging
logger = get_logger("BucketStorage")

# Configuration for the S3 client, including retry strategy
my_config = Config(
    region_name="auto",
    retries={"max_attempts": 10},
    s3={"addressing_style": "path"},
)

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB max file size


async def s3_client():
    """
    Create and return a new S3 client session with retries and region configuration.
    This function abstracts away the client initialization for reuse.

    Returns:
    boto3.S3.Client: Configured S3 client
    """
    logger.info("Creating S3 client session")
    session = aioboto3_session.Session()
    client = session.client(
        "s3",
        aws_access_key_id=settings.BUCKET_ACCESS_KEY_ID,
        aws_secret_access_key=settings.BUCKET_SECRET_ACCESS_KEY,
        endpoint_url=settings.R2_ENDPOINT_URL,
        config=my_config,
    )
    logger.info("S3 client session created successfully")
    return client


async def send_files(file, file_key, file_type):
    """
    Upload a file to the specified S3 bucket asynchronously.
    Automatically chooses between regular and multipart upload based on file size.

    Parameters:
    file (bytes): File content to upload.
    file_key (str): The path and file name for S3 (key).
    file_type (str): The MIME type of the file.
    Returns:
    dict: Response metadata from the S3 upload call.
    """
    file_size = len(file)

    # Use multipart upload for files larger than 10MB for better performance
    if file_size > (MAX_FILE_SIZE * 2):  # 10MB threshold
        logger.info(f"File size ({file_size} bytes) is large, using multipart upload")
        return await send_files_multipart(file, file_key, file_type)

    # Regular upload for smaller files
    logger.info(
        f"Uploading file to S3: {file_key} with type {file_type} (size: {file_size} bytes)"
    )
    try:
        async with await s3_client() as client:  # type: ignore
            upload_file_response = await client.put_object(
                Body=file,
                Bucket=settings.BUCKET_NAME,
                Key=file_key,
                ContentType=file_type,
            )
            logger.info(f"Successfully uploaded file to S3: {file_key}")
            logger.info(f"Upload response: {upload_file_response}")
            return upload_file_response
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(f"Error uploading file to S3: {file_key} - {e}")
        return {"error": str(e)}


def get_files(folder_slash_filename: str):
    """
    Generate a CloudFront URL for the given file in S3.

    Parameters:
    folder_slash_filename (str): The folder and file name (key) in S3.

    Returns:
    str: The full CloudFront URL for the file.
    """
    cloud_front_domain = settings.FILES_URL  # CloudFront domain
    url = f"{cloud_front_domain}/{folder_slash_filename}"
    return url  # Return the CloudFront URL


async def send_files_multipart(file, file_key, file_type, part_size=MAX_FILE_SIZE):  # pylint: disable=too-many-locals
    """
    Upload a large file to S3 using multipart upload for better performance.
    Falls back to regular upload for smaller files.

    Parameters:
    file (bytes): File content to upload.
    file_key (str): The path and file name for S3 (key).
    file_type (str): The MIME type of the file.
    part_size (int): Size of each part in bytes (default: 5MB).

    Returns:
    dict: Response metadata from the S3 upload.
    """
    file_size = len(file)

    logger.info(
        f"Uploading large file ({file_size} bytes) using multipart upload: {file_key}"
    )

    upload_id = None  # Initialize to None to avoid NameError in exception handling

    try:
        async with await s3_client() as client:  # type: ignore
            # Initiate multipart upload
            response = await client.create_multipart_upload(
                Bucket=settings.BUCKET_NAME,
                Key=file_key,
                ContentType=file_type,
            )
            upload_id = response["UploadId"]

            parts = []
            part_number = 1

            # Upload parts
            for i in range(0, file_size, part_size):
                part_data = file[i : i + part_size]

                part_response = await client.upload_part(
                    Bucket=settings.BUCKET_NAME,
                    Key=file_key,
                    PartNumber=part_number,
                    UploadId=upload_id,
                    Body=part_data,
                )

                parts.append({"ETag": part_response["ETag"], "PartNumber": part_number})

                logger.info(f"Uploaded part {part_number} for {file_key}")
                part_number += 1

            # Complete multipart upload
            complete_response = await client.complete_multipart_upload(
                Bucket=settings.BUCKET_NAME,
                Key=file_key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )

            logger.info(f"Successfully completed multipart upload for: {file_key}")
            return complete_response

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(f"Error in multipart upload for {file_key}: {e}")
        # Try to abort the multipart upload if it was initiated
        if upload_id:
            try:
                async with await s3_client() as client:  # type: ignore
                    await client.abort_multipart_upload(
                        Bucket=settings.BUCKET_NAME,
                        Key=file_key,
                        UploadId=upload_id,
                    )
                    logger.info(f"Aborted multipart upload {upload_id} for {file_key}")
            except Exception as abort_error:  # pylint: disable=broad-exception-caught
                logger.warning(
                    f"Failed to abort multipart upload {upload_id} for {file_key}: {abort_error}"
                )
        return {"error": str(e)}


async def delete_files(file_key: str):
    """
    Delete a file from the specified S3 bucket.

    Parameters:
    file_key (str): The path and file name for S3 (key).

    Returns:
    dict: Response metadata from the S3 `delete_object` call.
    """
    if not file_key:
        logger.error("No file_key provided for deletion.")
        return {"error": "No file_key provided."}
    try:
        async with await s3_client() as client:  # type: ignore
            delete_file_response = await client.delete_object(
                Bucket=settings.BUCKET_NAME,
                Key=file_key,
            )
            logger.info(f"Successfully deleted file from S3: {file_key}")
            return delete_file_response
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(f"Error deleting file from S3: {file_key} - {e}")
        return {"error": str(e)}
