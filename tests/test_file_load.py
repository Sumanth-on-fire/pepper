import requests
import urllib3

# Suppress insecure request warnings due to verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
if __name__=='__main__':
    public_url = 'https://sgp.cloud.appwrite.io/v1/storage/buckets/6a18270700352fd73cb5/files/6a66550200218ca3582f/view?project=6a15b6810010ba5db4dc'
    public_url2 = 'https://sgp.cloud.appwrite.io/v1/storage/buckets/6a18270700352fd73cb5/files/6a66550200218ca3582f/view?project=6a15b6810010ba5db4dc&impersonateuserid=&mode=admin'
    try:
        response = requests.get(url=public_url, headers={}, verify=False)
        print(response)
        # print(response.content)
        print(response.status_code)
        if response.status_code == 200:
            print('Loaded successfully')
        else:
            print("Failed to load")
    except Exception as e:
        print(e)
    