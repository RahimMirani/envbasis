interface UserLike {
  email?: string | null;
}

export function getUserDisplayName(user: UserLike | null | undefined): string {
  if (!user || !user.email) {
    return 'Unknown user';
  }

  const atIndex = user.email.indexOf('@');
  if (atIndex === -1) {
    return user.email;
  }

  return user.email.slice(0, atIndex);
}

export function getUserInitials(user: UserLike | null | undefined): string {
  const name = getUserDisplayName(user);
  const parts = name.split(/[\s._-]+/);

  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }

  return name.slice(0, 2).toUpperCase();
}
