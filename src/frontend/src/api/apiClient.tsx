import { headerBuilder, getApiUrl } from './config';

export class APIClientError extends Error {
    status: number;
    data: any;
    rawBody: string;

    constructor(message: string, status: number, data: any, rawBody: string) {
        super(message);
        this.name = 'APIClientError';
        this.status = status;
        this.data = data;
        this.rawBody = rawBody;
    }
}

// Helper function to build URL with query parameters
const buildUrl = (url: string, params?: Record<string, any>): string => {
    if (!params) return url;

    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
            searchParams.append(key, String(value));
        }
    });

    const queryString = searchParams.toString();
    return queryString ? `${url}?${queryString}` : url;
};

// Fetch with Authentication Headers
const fetchWithAuth = async (url: string, method: string = "GET", body: BodyInit | null = null) => {
    const authHeaders = headerBuilder(); // Get authentication headers

    const headers: Record<string, string> = {
        ...authHeaders, // Include auth headers from headerBuilder
    };

    // If body is FormData, do not set Content-Type header
    if (body && body instanceof FormData) {
        delete headers['Content-Type'];
    } else {
        headers['Content-Type'] = 'application/json';
        body = body ? JSON.stringify(body) : null;
    }

    const options: RequestInit = {
        method,
        headers,
        body: body || undefined,
    };

    try {
        const apiUrl = getApiUrl();
        const finalUrl = `${apiUrl}${url}`;
        // Log the request details
        const response = await fetch(finalUrl, options);

        const contentType = response.headers.get('content-type') || '';
        const isJson = contentType.includes('application/json');
        const rawBody = await response.text();
        let responseData: any = rawBody || null;
        if (isJson && rawBody) {
            try {
                responseData = JSON.parse(rawBody);
            } catch {
                responseData = rawBody;
            }
        }

        if (!response.ok) {
            const detailValue = typeof responseData === 'object' && responseData
                ? (responseData.detail ?? responseData.message ?? responseData)
                : (rawBody || 'Something went wrong');
            const detail = typeof detailValue === 'string' ? detailValue : JSON.stringify(detailValue);
            throw new APIClientError(detail, response.status, responseData, rawBody);
        }

        return responseData;
    } catch (error) {
        console.info('API Error:', (error as Error).message);
        throw error;
    }
};

// Vanilla Fetch without Auth for Login
const fetchWithoutAuth = async (url: string, method: string = "POST", body: BodyInit | null = null) => {
    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
    };

    const options: RequestInit = {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
    };

    try {
        const apiUrl = getApiUrl();
        const response = await fetch(`${apiUrl}${url}`, options);

        const contentType = response.headers.get('content-type') || '';
        const isJson = contentType.includes('application/json');
        const rawBody = await response.text();
        let responseData: any = rawBody || null;
        if (isJson && rawBody) {
            try {
                responseData = JSON.parse(rawBody);
            } catch {
                responseData = rawBody;
            }
        }
        if (!response.ok) {
            const detailValue = typeof responseData === 'object' && responseData
                ? (responseData.detail ?? responseData.message ?? responseData)
                : (rawBody || 'Login failed');
            const detail = typeof detailValue === 'string' ? detailValue : JSON.stringify(detailValue);
            throw new APIClientError(detail, response.status, responseData, rawBody);
        }
        return responseData;
    } catch (error) {
        console.log('Login Error:', (error as Error).message);
        throw error;
    }
};

// Authenticated requests (with token) and login (without token)
export const apiClient = {
    get: (url: string, config?: { params?: Record<string, any> }) => {
        const finalUrl = buildUrl(url, config?.params);
        return fetchWithAuth(finalUrl, 'GET');
    },
    post: (url: string, body?: any) => fetchWithAuth(url, 'POST', body),
    put: (url: string, body?: any) => fetchWithAuth(url, 'PUT', body),
    delete: (url: string) => fetchWithAuth(url, 'DELETE'),
    upload: (url: string, formData: FormData) => fetchWithAuth(url, 'POST', formData),
    login: (url: string, body?: any) => fetchWithoutAuth(url, 'POST', body), // For login without auth
};
