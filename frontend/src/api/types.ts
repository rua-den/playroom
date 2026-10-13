export interface Owner {
  id: string;
  email: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface ApiErrorBody {
  detail?: string | Array<{ msg?: string }>;
  code?: string;
}
