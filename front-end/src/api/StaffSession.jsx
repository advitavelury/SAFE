import { createContext, useContext } from 'react';

export const StaffSession = createContext(null);
export const useStaffSession = () => useContext(StaffSession);
