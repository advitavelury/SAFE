export function isApprovedStaff(user, profile) {
  return Boolean(user && !user.isAnonymous && profile?.active === true
    && ["admin", "operator"].includes(profile.role));
}

export function canEditIncidents(user, profile) {
  return isApprovedStaff(user, profile) && profile.role === 'admin';
}

// A generation counter prevents a previous account's late callbacks from
// restoring access after sign-out, account switching, or component teardown.
export function watchStaffAccess({ watchAuth, watchProfile }, emit) {
  let generation = 0;
  let stopProfile;
  const stopAuth = watchAuth((user) => {
    const current = ++generation;
    stopProfile?.();
    stopProfile = undefined;
    if (!user || user.isAnonymous) {
      emit({ status: "signed-out", user: null });
      return;
    }
    emit({ status: "checking", user });
    stopProfile = watchProfile(user.uid, (profile, fromCache) => {
      if (current !== generation) return;
      if (fromCache) {
        emit({ status: "checking", user });
        return;
      }
      emit({ status: isApprovedStaff(user, profile) ? "ready" : "denied", user, profile });
    }, () => {
      if (current === generation) emit({ status: "error", user });
    });
  }, () => {
    generation++;
    stopProfile?.();
    emit({ status: "error", user: null });
  });
  return () => {
    generation++;
    stopProfile?.();
    stopAuth();
  };
}
