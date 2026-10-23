export type CurrentUser = {
  open_id: string;
  name: string;
  avatar_url: string;
  department_ids: string[];
  department_paths: string[];
  roles: string[];
  permission_status: "enabled" | "disabled" | "missing";
};

export type SelectableUser = Pick<
  CurrentUser,
  "open_id" | "name" | "department_ids" | "department_paths"
>;

export function withCurrentUser<T extends SelectableUser>(
  users: T[],
  currentUser: CurrentUser | null,
): SelectableUser[] {
  if (!currentUser || users.some((user) => user.open_id === currentUser.open_id)) {
    return users;
  }
  return [currentUser, ...users];
}
